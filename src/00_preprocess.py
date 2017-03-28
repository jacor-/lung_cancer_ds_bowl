"""
File for preprocessing the datasets. It gets as input the DCOMS path, and converts it to numpy.


Datasets accepted: ['dsb', 'lidc', 'luna']

Example usage:
python 00_preprocess.py --input=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/luna/subset0 --output=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/preproc_luna --pipeline=luna --nodules=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/luna/annotations.csv
python 00_preprocess.py --input=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/sample_images --output=/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/preproc_dsb --pipeline=dsb

python 00_preprocess.py --input=/home/shared/data/luna/images --output=/mnt/hd2/preprocessed5/ --pipeline=luna --nodules=/home/shared/data/luna/annotations.csv
python 00_preprocess.py --input=/home/shared/data/stage1 --output=/mnt/hd2/preprocessed5/ --pipeline=dsb
"""

import os
import sys
from glob import glob
from time import time
import SimpleITK as sitk
import numpy as np
import pandas as pd
from utils import preprocessing
from utils import reading
from utils import lung_segmentation

import matplotlib.pyplot as plt
from utils import plotting


# Define folder locations
wp = os.environ.get('LUNG_PATH', '')
TMP_FOLDER = os.path.join(wp, 'data/jm_tmp/')
INPUT_FOLDER = os.path.join(wp, 'data/luna/luna0123')
OUTPUT_FOLDER = os.path.join(wp, 'data/stage1_proc/')
NODULES_PATH = os.path.join(wp, 'data/luna/annotations.csv')

# Define parametres
PIPELINE = 'dsb'  # for filename
COMMON_SPACING = [2, 0.7, 0.7]

# Execution parameters
SAVE_RESULTS = True

# Overwriting parameters by console
for arg in sys.argv[1:]:
    if arg.startswith('--input='):
        INPUT_FOLDER = ''.join(arg.split('=')[1:])
    elif arg.startswith('--output='):
        OUTPUT_FOLDER = ''.join(arg.split('=')[1:])
    elif arg.startswith('--tmp='):
        TMP_FOLDER = ''.join(arg.split('=')[1:])
    elif arg.startswith('--pipeline='):
        PIPELINE = ''.join(arg.split('=')[1:])
    elif arg.startswith('--debug'):
        DEBUG_IMAGES = True
    elif arg.startswith('--nodules='):
        NODULES_PATH = ''.join(arg.split('=')[1:])
    else:
        print('Unknown argument {}. Ignoring.'.format(arg))


if PIPELINE == 'dsb':
    patient_files = os.listdir(INPUT_FOLDER)
elif PIPELINE == 'lidc':
    patient_files = os.listdir(INPUT_FOLDER)
    try:
        df_nodules = pd.read_csv(NODULES_PATH)
        df_nodules.index = df_nodules['case']
    except Exception as e:
        print (e)
        print ('There are no nodules descriptor in this dataset.')
elif PIPELINE == 'luna':
    patient_files = glob(INPUT_FOLDER + '/*.mhd')  # patients from subset
    df_nodules = pd.read_csv(NODULES_PATH)

## get IDS in the output folder to avoid recalculating them
current_ids = glob(OUTPUT_FOLDER + '/*.npz')
current_ids = [x.split('_')[-1].replace('.npz', '') for x in current_ids]


for p in patient_files:
    if '303421828981831854739626597495' in p:
        print p
patient_file = '/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/luna/luna0123/1.3.6.1.4.1.14519.5.2.1.6279.6001.122621219961396951727742490470.mhd'
patient_file = '/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/luna/luna0123/1.3.6.1.4.1.14519.5.2.1.6279.6001.935683764293840351008008793409.mhd'
patient_file = '/Users/mingot/Projectes/kaggle/ds_bowl_lung/data/luna/luna0123/1.3.6.1.4.1.14519.5.2.1.6279.6001.303421828981831854739626597495.mhd'

# Main loop over the ensemble of the database
times = []
for patient_file in patient_files:
    
    tstart = time()
    nodule_mask = None
    print('Trying patient: {}'.format(patient_file))
    
    # Read
    try:
        if PIPELINE == 'dsb':
            patient = reading.load_scan(os.path.join(INPUT_FOLDER, patient_file))
            patient_pixels = preprocessing.get_pixels_hu(patient)  # From pixels to HU
            originalSpacing = reading.dicom_get_spacing(patient)
            pat_id = patient_file

        elif PIPELINE == 'luna':
            patient = sitk.ReadImage(patient_file) 
            patient_pixels = sitk.GetArrayFromImage(patient)  # indexes are z,y,x
            originalSpacing = [patient.GetSpacing()[2], patient.GetSpacing()[0], patient.GetSpacing()[1]]
            pat_id = patient_file.split('.')[-2]

            # load nodules
            seriesuid = patient_file.split('/')[-1].replace('.mhd', '')
            nodules = df_nodules[df_nodules["seriesuid"] == seriesuid]  # filter nodules for patient
            nodule_mask = reading.create_mask(img=patient, nodules=nodules)

        elif PIPELINE == 'lidc':
            patient = reading.read_patient_lidc(os.path.join(INPUT_FOLDER, patient_file))
            patient_pixels = preprocessing.get_pixels_hu(patient)  # From pixels to HU
            originalSpacing = reading.dicom_get_spacing(patient)
            pat_id = patient_file
            pat_id_nr = int(pat_id[-4:])
            nodules = reading.read_nodules_lidc(df_nodules, pat_id_nr, patient[0].SeriesNumber, originalSpacing)

            # Dimensions
            zSize = len(patient)
            xSize = patient[0].Rows
            ySize = patient[0].Columns # or the other way around

            # Generate the nodule mask
            nodule_mask = np.zeros((zSize, xSize, ySize), dtype=np.uint8)
        
            for pixel_coordinates, diameter in nodules:
                nodule_point_list = reading.ball(diameter / 2,  pixel_coordinates, originalSpacing)
                nodule_mask = reading.draw_in_mask(nodule_mask, nodule_point_list)

    except Exception as e:  # Some patients have no data, ignore them
        print('There was some problem reading patient {}. Ignoring and live goes on.'.format(patient_file))
        print('Exception', e)
        continue

    # avoid computing the id if not already present
    if pat_id in current_ids:
        continue

    # SET BACKGROUND: set to air parts that fell outside
    patient_pixels[patient_pixels < -1500] = -2000


    # RESAMPLING
    pix_resampled, new_spacing = preprocessing.resample(patient_pixels, spacing=originalSpacing, new_spacing=COMMON_SPACING)
    if nodule_mask is not None:
        nodule_mask, new_spacing = preprocessing.resample(nodule_mask, spacing=originalSpacing, new_spacing=COMMON_SPACING)
    print('Resampled image size: {}'.format(pix_resampled.shape))


    # LUNG SEGMENTATION
    tstart = time()
    lung_mask = lung_segmentation.segment_lungs(image=pix_resampled, fill_lung=True, method="thresholding1")  # thresholding1, thresholding2, watershed
    # TODO: if lung_mask fails, do it with thresholding2
    print "Time segmenting lungs: %.4f" % (time() - tstart)

    # Checks for lung segmentation
    voxel_volume_l = COMMON_SPACING[0]*COMMON_SPACING[1]*COMMON_SPACING[2]/(1000000.0)  # Check 1: volume
    lung_volume_l = np.sum(lung_mask)*voxel_volume_l
    if lung_volume_l < 2 or lung_volume_l > 10:
        print('ERROR LUNG MASK: Lung volume for patient {} out of physiological values.'.format(pat_id))
    for nslice in range(pix_resampled.shape[0]):  # Check 2: nodules inside lung_mask
        if nodule_mask is not None and np.sum(nodule_mask[nslice])>0 and np.sum(lung_mask[nslice]*nodule_mask[nslice])==0:
            print('ERROR LUNG MASK: Nodules outside the mask in patient %s, slice %d' % (pat_id, nslice))

    # CROPPING to 512x512
    pix = preprocessing.resize_image(pix_resampled, size=512)  # if zero_centered: -0.25
    lung_mask = preprocessing.resize_image(lung_mask, size=512)
    if nodule_mask is not None:
        nodule_mask = preprocessing.resize_image(nodule_mask, size=512)
    print('Cropped image size: {}'.format(pix.shape))

    # Load nodules, after resampling to do it faster.
    # try:
    #     nodule_mask_ok = False
    #     if PIPELINE == 'lidc':
    #         nodule_list = reading.read_nodules_lidc(nodules, int(pat_id[-4:]), patient[0].SeriesNumber,
    #                                                 originalSpacing)
    #     else:
    #         print 'Unsupported nodules loading!'
    #         raise Exception('no nodules')
    #
    #     nodule_mask = np.zeros(pix.shape ,dtype = np.dtype(bool))
    #     #transform the old voxel coordinates to the new system
    #     #TODO: improve, I think there might be some loses due to precision
    #     for nodule_world_coordinates, d in nodule_list:
    #         voxel_coordinates = nodule_world_coordinates/new_spacing
    #         voxel_coordinates_integer = np.floor(voxel_coordinates).astype(int)
    #         print 'nodule at position', voxel_coordinates_integer, d
    #         voxel_coordinates_residual = voxel_coordinates - voxel_coordinates_integer
    #
    #         ball_voxels = reading.ball(d/2, voxel_coordinates_residual, new_spacing)
    #         for p in ball_voxels:
    #             indices = p + voxel_coordinates_integer
    #             nodule_mask[indices[0], indices[1], indices[2]] = True
    #     nodule_mask_ok = True
    # except Exception as e:
    #     print e
    #     pass
    
    # store output (processed lung and lung mask)
    if nodule_mask is None and PIPELINE=='luna':
        # create virtual nodule mask for coherence
        nodule_mask = np.zeros(pix.shape, dtype=np.int)

    if nodule_mask is None:
        output = np.stack((pix, lung_mask))
    else:
        output = np.stack((pix, lung_mask, nodule_mask))


    if SAVE_RESULTS:
        np.savez_compressed(os.path.join(OUTPUT_FOLDER, "%s_%s.npz") % (PIPELINE, pat_id), output)
        # 10x compression over np.save (~400Mb vs 40Mb), but 10x slower  (~1.5s vs ~15s)

    x = time()-tstart
    print('Patient {}, Time: {}'.format(pat_id, x))
    times.append(x)

print('Average time per image: {}'.format(np.mean(times)))

