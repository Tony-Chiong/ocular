from collections import namedtuple
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
import preprocessing.searchgrid as search
from eval.timing import timed_block
from featureselection import mifs
from featureselection.mnecsp import csp_one_vs_all
from preprocessing.dataextractor import load_data, restructure_data, extract_eog, d3_matrix_creator
from classification.randomforrest import rfl_one_versus_all, rfl_prediction
from preprocessing.filter import Filter
from preprocessing.trial_remaker import remake_trial, remake_single_run_transform
from itertools import chain
from multiprocessing import freeze_support
from sklearn import cross_validation
from numpy import array
from preprocessing.oaclbase import OACL
import os
import filehandler
import numpy as np

optimize_params = True


def main(*args):
    print 'Running with following args \n'
    print args
    named_grid = namedtuple('Grid', ['n_comp', 'C', 'kernel', 'band_list', 'oacl_ranges', 'm'])
    search.grid = named_grid(*args)
    runs, evals, thetas = '', '', ''

    old_path = os.getcwd()
    os.chdir('..')

    # Load args from search-grid
    oacl_ranges = search.grid.oacl_ranges if 'oacl_ranges' in search.grid._fields else ((3, 7), (7, 15))
    m = search.grid.m if 'm' in search.grid._fields else 11
    C = search.grid.C if 'C' in search.grid._fields else 1
    kernel = search.grid.kernel if 'kernel' in search.grid._fields else 'linear'
    filt = search.grid.band_list if 'band_list' in search.grid._fields else [[8, 12], [16, 24]]
    n_comp = search.grid.n_comp if 'n_comp' in search.grid._fields else 3

    # Generate a name for serializing of file
    filename_suffix = filehandler.generate_filename(oacl_ranges, m)

    # Check whether the data is already present as serialized data
    # If not run OACL and serialize, else load data from file
    if filehandler.file_is_present('runs' + filename_suffix) is False:
        with timed_block('Iteration '):
            runs = load_data(8, "T")
            eog_test, runs = extract_eog(runs)
            runs, train_oacl = remake_trial(runs)

            thetas = train_oacl.trial_thetas

            evals = load_data(8, "E")
            eog_eval, evals = extract_eog(evals)
            evals, test_oacl = remake_trial(evals, arg_oacl=train_oacl)

        # Save data, could be a method instead
        filehandler.save_data(runs, 'runs' + filename_suffix)
        filehandler.save_data(evals, 'evals' + filename_suffix)
        filehandler.save_data(thetas, 'thetas' + filename_suffix)
    else:
        runs = filehandler.load_data('runs' + filename_suffix)
        evals = filehandler.load_data('evals' + filename_suffix)
        thetas = filehandler.load_data('thetas' + filename_suffix)

    run_choice = range(3, 9)

    sh = cross_validation.ShuffleSplit(6, n_iter=6, test_size=0.16)

    accuracies = []
    for train_index, test_index in sh:
        csp_list = []

        train = array(runs)[array(run_choice)[(sorted(train_index))]]
        test = load_data(8, "T")
        eog_test, test = extract_eog(test)
        test = array(test)[array(run_choice)[test_index]]

        oacl = OACL(ranges=oacl_ranges, m=m, multi_run=True)
        oacl.theta = oacl.generalize_thetas(array(thetas)[train_index])

        test = remake_single_run_transform(test, oacl)

        filters = Filter(filt)


        train_bands, train_combined_labels = restructure_data(train, filters)
        test_bands, test_combined_labels = restructure_data(test, filters)

        for band in train_bands:
            csp_list.append(csp_one_vs_all(band, 4, n_comps=n_comp))

        feature_list = []
        temp = []
        for band, csp in zip(train_bands, csp_list):
            d3_matrix = d3_matrix_creator(band[0], len(band[1]))
            for single_csp in csp:
                temp.append(single_csp.transform(d3_matrix))
            feature_list.append(temp)
            temp = []

        combi_csp_class_features = []
        for x in zip(*feature_list):
            combi_csp_class_features.append(array([list(chain(*z)) for z in zip(*x)]))

        mifs_list = []
        for j in range(len(combi_csp_class_features)):
            # TODO: figure out which method should be used
            MIFS = mifs.MutualInformationFeatureSelector(method="JMI", verbose=2, categorical=True, n_features=4)
            MIFS.fit(combi_csp_class_features[j], array([0 if j == i - 1 else 1 for i in train_combined_labels]))

            # Include all components of each CSP where at least one of its components has been selected
            selection = MIFS.support_
            b = len(filt)
            m = n_comp
            temp = [selection[i:i+m] for i in range(0, m*b, m)]
            temp2 = [[True] * m if True in temp[i] else [False] * m for i in range(b)]
            MIFS.support_ = array(list(chain(*temp2)))

            combi_csp_class_features[j] = MIFS.transform(combi_csp_class_features[j])
            mifs_list.append(MIFS)

        feature_list = []
        temp = []
        for band, csp in zip(test_bands, csp_list):
            d3_matrix = d3_matrix_creator(band[0], len(band[1]))
            for single_csp in csp:
                temp.append(single_csp.transform(d3_matrix))
            feature_list.append(temp)
            temp = []

        combi_csp_class_features_test = []
        for x in zip(*feature_list):
            combi_csp_class_features_test.append(array([list(chain(*z)) for z in zip(*x)]))

        svc_list = []
        for i in range(len(combi_csp_class_features)):
            svc = SVC(C=C, kernel=kernel, gamma='auto', probability=True)
            scaled = StandardScaler().fit_transform(combi_csp_class_features[i].tolist())
            svc.fit(scaled, [0 if j - 1 == i else 1 for j in train_combined_labels])
            svc_list.append(svc)

        for i in range(len(combi_csp_class_features_test)):
            combi_csp_class_features_test[i] = mifs_list[i].transform(combi_csp_class_features_test[i])

        proba = []
        for i in range(len(combi_csp_class_features)):
            svc = svc_list[i]
            scaled = StandardScaler().fit_transform(combi_csp_class_features_test[i].tolist())
            temp_proba = []
            for j in range(len(scaled)):
                temp_proba.append(svc.predict_proba(scaled[j]))
            proba.append(temp_proba)

        predictions = []
        for prob in zip(*proba):
            prob = [p[0][0] for p in prob]
            maxprob = max(prob)
            idx = prob.index(maxprob)
            predictions.append(idx + 1)

        accuracy = np.mean([1 if a == b else 0 for (a, b) in zip(predictions, test_combined_labels)])
        print("Accuracy: " + str(accuracy) + "%")

        accuracies.append(accuracy)

    return np.mean(accuracies) * 100



if __name__ == '__main__':
    freeze_support()
    main(2, 0.1, 'rbf', [[4, 8], [8, 12], [12, 16], [16, 20], [20, 30]], ((3, 7), (7, 15)), 11)
