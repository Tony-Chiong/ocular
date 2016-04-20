import os
import subprocess
from time import sleep
from real_main import main


band_sample = [[[8, 12], [12, 16], [16, 20], [20, 24]]]
band_sample += [[8, 12], [12, 16], [16, 20], [20, 24], [24, 28]]
band_sample += [[4, 8], [8, 12], [12, 16], [16, 20], [20, 24], [24, 28], [28, 32]]

kernel_sample = ['linear', 'rbf', 'poly']


def optim_params():
    while True:
        old_path = os.getcwd()
        print os.getcwd()
        os.chdir('../spearmintlite')
        command = 'python spearmintlite.py ../braninpy'
        subprocess.call(command, shell=True)
        sleep(2)
        os.chdir(old_path)

        params = get_params()
        par = params.split(' ')
        n_comp = int(par[2])
        c = float(par[3])
        kernel = kernel_sample[int(par[4])]
        band_list = band_sample[int(par[5])]
        r1 = int(par[6])
        r2 = int(par[7])
        r3 = int(par[8])
        r4 = int(par[9])
        m = int(par[10])
        oacl_ranges = ((r1, r2), (r3, r4))

        result, time = main(n_comp, c, kernel, band_list, oacl_ranges, m)

        insert_result(result, time)
        sleep(2)


def get_params():
    with open('../braninpy/results.dat', 'rb') as fh:
        last_line = ''
        for line in fh:
            last_line = line

    return last_line


def insert_result(result, time):
    file = "../braninpy/results.dat"

    # read the file into a list of lines
    lines = open(file, 'r').readlines()

    # now edit the last line of the list of lines
    last_line_list = lines[-1].rstrip().split(' ')
    last_line_list[0] = 100 - result
    last_line_list[1] = time
    print last_line_list
    last_line_string = ' '.join(map(str, last_line_list))
    lines[-1] = last_line_string + ' \n'
    print last_line_string
    # now write the modified list back out to the file
    open(file, 'w').writelines(lines)

optim_params()