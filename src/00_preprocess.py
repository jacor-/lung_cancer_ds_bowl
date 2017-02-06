"""
File for preprocessing the datasets. It gets as input the DCOMS path, and converts it to numpy.


Datasets accepted:
    -DSB
    -LIDC
    -LUNA
    
Example usage:
python 00_preprocess.py --input=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/luna/subset0 --output=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/preproc_luna --pipeline=luna
python 00_preprocess.py --input=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/sample_images --output=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/preproc_dsb --pipeline=dsb

python 00_preprocess.py --input=/home/shared/data/luna --output=/home/shared/data/preprocess --pipeline=luna
python 00_preprocess.py --input=/home/shared/data/stage1 --output=/mnt/hd2/preprocessed/ --pipeline=dsb
"""

def extend_512(img, val=-0.25):
    result = np.zeros((img.shape[0],512, 512))
    result.fill(val)
    
    x = (512 - img.shape[1])/2
    y = (512 - img.shape[2])/2
    result[:, x:x+img.shape[1], y:y+img.shape[2] ] = img
    return result
    
    
accepted_datasets = ['dsb', 'lidc', 'luna']

import os
import numpy as np
from time import time
from utils import reading
from utils import preprocessing
from utils import plotting
import matplotlib.pyplot as plt
import sys
from glob import glob
import SimpleITK as sitk

# Define folder locations
wp = os.environ['LUNG_PATH']
TMP_FOLDER = os.path.join(wp, 'data/jm_tmp/')
INPUT_FOLDER = os.path.join(wp, 'data/stage1/')  # 'data/stage1/stage1/'
OUTPUT_FOLDER = os.path.join(wp, 'data/stage1_proc/')
PIPELINE = 'dsb'  # for filename
show_intermediate_images = False  # Execution parameters


# Overwriting parameters by console
for arg in sys.argv[1:]:
    if arg.startswith('--input='):
        INPUT_FOLDER = ''.join(arg.split('=')[1:])
    elif arg.startswith('--output='):
        OUTPUT_FOLDER = ''.join(arg.split('=')[1:])
    elif arg.startswith('--tmp='):
        TMP_FOLDER =''.join(arg.split('=')[1:])
    elif arg.startswith('--pipeline='):
        PIPELINE = ''.join(arg.split('=')[1:])
    elif arg.startswith('--debug'):
        show_intermediate_images = True
    else:
        print 'Unknown argument %s. Ignoring.' %arg
        
        
if PIPELINE not in accepted_datasets:
    print 'Error, preprocessing ofdataset %s not implemented' % PIPELINE 
        
if PIPELINE in ['dsb', 'lidc'] :
    patient_files = os.listdir(INPUT_FOLDER)
elif PIPELINE == 'luna':
    patient_files = glob(wp + 'data/luna/subset1/*.mhd')  # patients from subset1


# Main loop over the ensemble of teh database
times = []
for patient_file in patient_files:
    
    n = time()
    
    # Read
    # patid = patients[10]
    try:
        if PIPELINE == 'dsb':
            patient = reading.load_scan(os.path.join(INPUT_FOLDER, patient_file))

            spacing = reading.dicom_get_spacing(patient)
            pat_id = patient_file

        elif PIPELINE == 'luna':
            patient = sitk.ReadImage(patient_file) 
            patient_pixels = sitk.GetArrayFromImage(patient) #indexes are z,y,x
            spacing = [patient.GetSpacing()[2], patient.GetSpacing()[0], patient.GetSpacing()[1]]
            pat_id = patient_file.split('.')[-2]

        elif PIPELINE == 'lidc':
            patient = reading.read_patient_lidc(os.path.join(INPUT_FOLDER, patient_file))
            spacing = reading.dicom_get_spacing(patient)
            pat_id = patient_file
                
    except Exception as e:
        print 'There was some problem reading patient %s. Ignoring and live goes on.' % (patient_file)
        print e
        # Some patients have no data, ignore them
        continue
    
    if PIPELINE != 'luna':
        # From pixels to HU
        patient_pixels = preprocessing.get_pixels_hu(patient)
        if show_intermediate_images:
            print("Shape of raw data\t", patient_pixels.shape)
            plt.figure()
            plt.imshow(patient_pixels[3])
            plt.title('Raw pixel data')
            plt.figure()
            plt.hist(patient_pixels.flatten(), bins=80, color='c')
            plt.title('Histogram')

    # Resampling
    # TODO: Accelerate the resampling
    pix_resampled, spacing = preprocessing.resample(patient_pixels, spacing=spacing, new_spacing=[1, 1, 1])
    if show_intermediate_images:
        print("Shape after resampling\t", pix_resampled.shape)
        plt.figure()
        plt.imshow(pix_resampled[50])
        plt.title('Resampled data')
        # plt.figure()
        # plotting.plot_3d(pix_resampled, 400)
    
    # Segment lungs
    lung_mask = preprocessing.segment_lung_mask(pix_resampled, fill_lung_structures=True)
    if show_intermediate_images:
        print("Size of the mask\t", lung_mask.shape)
        plt.figure()
        plt.imshow(lung_mask[90])
        # plotting.plot_3d(segmented_lungs_fill, 0)
        # plotting.plot_3d(segmented_lungs_fill - segmented_lungs, 0)
    
    # Compute volume for sanity test
    lung_volume_l = np.sum(lung_mask)/(100.**3)
    if lung_volume_l < 2 or lung_volume_l > 10:
        print("Warning lung volume: %s out of physiological values. Double Check segmentation.", pat_id)
    
    # zero center and normalization
    pix = preprocessing.normalize(pix_resampled)
    pix = preprocessing.zero_center(pix)
    
    # extend to 512
    pix = extend_512(pix, val=-0.25)
    lung_mask = extend_512(lung_mask, val=0)
    
    # store output (processed lung and lung mask)
    output = np.stack((pix, lung_mask))
    # TODO: The following line crashes if the output folder does not exist
    np.savez_compressed(os.path.join(OUTPUT_FOLDER, "%s_%s.npz") % (PIPELINE, pat_id), output)  # 10x compression over np.save (~400Mb vs 40Mg), but 10x slower  (~1.5s vs ~15s)
    # np.save("prova.npy", output)
    
    x = time()-n
    print("Time: %s", str(x))
    times.append(x)

print("Average time per image: %s", str(np.mean(times)))
