import cPickle
from collections import namedtuple

from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

import preprocessing.searchgrid as search
from classification.svm import csv_one_versus_all, svm_prediction
from eval.score import scoring
from eval.timing import timed_block
from eval.voting import csp_voting
from featureselection import mifs
from featureselection.mnecsp import csp_one_vs_all
from preprocessing.dataextractor import load_data, restructure_data, extract_eog, d3_matrix_creator
from classification.randomforrest import rfl_one_versus_all, rfl_prediction
from preprocessing.filter import Filter
from preprocessing.trial_remaker import remake_trial, remake_single_run_transform
from os import listdir
from random import shuffle
from itertools import chain
from os.path import isfile, join
from multiprocessing import freeze_support
from sklearn import cross_validation
from numpy import array
from preprocessing.oaclbase import OACL
import os
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

    oacl_ranges = search.grid.oacl_ranges
    pickel_file_name = str(oacl_ranges[0][0]) + str(oacl_ranges[0][1]) + str(oacl_ranges[1][0])
    pickel_file_name += str(oacl_ranges[1][1]) + str(search.grid.m) + '.dump'
    if not os.path.isdir('pickelfiles'):
        os.mkdir('pickelfiles')
    onlyfiles = [f for f in listdir('pickelfiles') if isfile(join('pickelfiles', f))]
    if len(onlyfiles) >= 100:
        file_to_delete1 = onlyfiles[0].replace('evals', '')
        file_to_delete1 = file_to_delete1.replace('runs', '')
        file_to_delete2 = 'runs' + file_to_delete1
        file_to_delete1 = 'evals' + file_to_delete1
        os.remove('pickelfiles/' + file_to_delete1)
        os.remove('pickelfiles/' + file_to_delete2)
        onlyfiles.remove(file_to_delete1)
        onlyfiles.remove(file_to_delete2)
    if 'runs' + pickel_file_name not in onlyfiles:
        with timed_block('Iteration '):
            runs = load_data(8, "T")
            eog_test, runs = extract_eog(runs)
            runs, train_oacl = remake_trial(runs)

            thetas = train_oacl.trial_thetas

            evals = load_data(8, "E")
            eog_eval, evals = extract_eog(evals)
            evals, test_oacl = remake_trial(evals, arg_oacl=train_oacl)

        # Save data, could be a method instead
        with open('pickelfiles/runs' + pickel_file_name, "wb") as output:
            cPickle.dump(runs, output, cPickle.HIGHEST_PROTOCOL)

        with open('pickelfiles/evals' + pickel_file_name, "wb") as output:
            cPickle.dump(evals, output, cPickle.HIGHEST_PROTOCOL)

        with open('pickelfiles/thetas' + pickel_file_name, 'wb') as output:
            cPickle.dump(thetas, output, cPickle.HIGHEST_PROTOCOL)
    else:
        with open('pickelfiles/runs' + pickel_file_name, "rb") as input:
            runs = cPickle.load(input)

        with open('pickelfiles/evals' + pickel_file_name, "rb") as input:
            evals = cPickle.load(input)

        with open('pickelfiles/thetas' + pickel_file_name, 'rb') as input:
            thetas = cPickle.load(input)

    run_choice = range(3, 9)

    sh = cross_validation.ShuffleSplit(6, n_iter=6, test_size=0.16)

    for train_index, test_index in sh:
        csp_list = []

        train = array(runs)[array(run_choice)[(sorted(train_index))]]
        test = load_data(8, "T")
        eog_test, test = extract_eog(test)
        test = array(test)[array(run_choice)[test_index]]

        C = search.grid.C if 'C' in search.grid._fields else 1
        kernel = search.grid.kernel if 'kernel' in search.grid._fields else 'linear'
        m = search.grid.m if 'm' in search.grid._fields else 11
        ranges = search.grid.oacl_ranges if 'oacl_ranges' in search.grid._fields else ((3, 7), (7, 15))
        oacl = OACL(ranges=ranges, m=m, multi_run=True)
        oacl.theta = oacl.generalize_thetas(array(thetas)[train_index])
        test = remake_single_run_transform(test, oacl)

        filt = search.grid.band_list if 'band_list' in search.grid._fields else [[8, 12], [16, 24]]
        filters = Filter(filt)

        n_comp = search.grid.n_comp if 'n_comp' in search.grid._fields else 3

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


        print "Done so far"


    # os.chdir(old_path)
    #
    # with timed_block('All Time'):
    #     # for subject in [int(x) for x in range(1, 2)]:
    #     csp_list = []
    #     svc_list = []
    #     rfl_list = []
    #     filt = search.grid.band_list if 'band_list' in search.grid._fields else [[8, 12], [16, 24]]
    #     filters = Filter(filt)
    #
    #     train_bands, train_combined_labels = restructure_data(runs, filters)
    #
    #     test_bands, test_combined_labels = restructure_data(evals, filters)
    #
    #     # CSP one VS all, give csp_one_cs_all num_different labels as input
    #
    #
    #     # Create a svm for each csp and band
    #     for csp, band in zip(csp_list, train_bands):
    #         svc_list.append(csv_one_versus_all(csp, band))
    #
    #     # Create a random forest tree for each csp and band
    #     for csp, band in zip(csp_list, train_bands):
    #         rfl_list.append(rfl_one_versus_all(csp, band))
    #
    #     # Predict results with svm's
    #     svm_results = svm_prediction(test_bands, svc_list, csp_list)
    #
    #     # Predict results with svm's
    #     rfl_results = rfl_prediction(test_bands, rfl_list, csp_list)
    #
    #     svm_voting_results = csp_voting(svm_results)
    #     rfl_voting_results = csp_voting(rfl_results)
    #
    #     svm_score, wrong_list = scoring(svm_voting_results, test_combined_labels)
    #     rfl_score, wrong_list = scoring(rfl_voting_results, test_combined_labels)
    #     score = svm_score if svm_score >= rfl_score else rfl_score
    # print search.grid
    # print 'rfl results: ' + str(rfl_score)
    # print 'svm results ' + str(svm_score)
    # print '\n'
    # print 'Best score: ' + str(score)
    # return svm_score, 1200

if __name__ == '__main__':
    freeze_support()
    main(2, 0.1, 'rbf', [[4, 8], [8, 12], [12, 16], [16, 20], [20, 30]], ((3, 7), (7, 15)), 11)


def check_selection(selected, i, r):
    """
    Check FN, FP, TP ratios among the selected features.
    """
    # reorder selected features
    try:
        selected = set(selected)
        all_f = set(range(i+r))
        TP = len(selected.intersection(all_f))
        FP = len(selected - all_f)
        FN =  len(all_f - selected)
        if (TP+FN) > 0:
            sens = TP/float(TP + FN)
        else:
            sens = np.nan
        if (TP+FP) > 0:
            prec =  TP/float(TP + FP)
        else:
            prec = np.nan
    except:
        sens = np.nan
        prec = np.nan
    return sens, prec
