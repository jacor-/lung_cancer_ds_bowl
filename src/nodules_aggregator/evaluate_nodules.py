# Read .csv containing detected nodules on LUNA and compute
#   confusion matrix for it

import pandas as pd
import numpy as np
import os
from math import ceil
from dl_utils.heatmap import extract_regions_from_heatmap
from sklearn import metrics
import matplotlib.pyplot as plt


## PATHS AND FILES
wp = os.environ['LUNG_PATH']
DATA_PATH = '/mnt/hd2/preprocessed5/'  # DATA_PATH = wp + 'data/preprocessed5_sample/'
NODULES_FILE = "/home/mingot/output/noduls_patches_v05_backup3.csv"  # NODULES_FILE = wp + 'personal/noduls_patches_v04_dsb.csv'
df_node = pd.read_csv(NODULES_FILE, skiprows=[1977535])  # TODO: remove the skipeed row
file_list = [g for g in os.listdir(DATA_PATH) if g.startswith('luna_')]
filenames_scored_full = set(df_node['filename'])

## Filter nodules
SCORE_THRESHOLD = 0.8
# df_node = df_node[df_node['score']>SCORE_THRESHOLD]
filenames_scored = set(df_node['filename'])

## Auxiliar functions
class AuxRegion():
    def __init__(self, dim):
        self.bbox = dim

def intersection_regions(r1, r2):
    h = min(r1.bbox[2], r2.bbox[2]) - max(r1.bbox[0], r2.bbox[0])
    w = min(r1.bbox[3], r2.bbox[3]) - max(r1.bbox[1], r2.bbox[1])
    intersectionArea = w*h
    if h<0 or w<0:
        return 0.0

    area1 = (r1.bbox[2] - r1.bbox[0])*(r1.bbox[3] - r1.bbox[1])
    area2 = (r2.bbox[2] - r2.bbox[0])*(r2.bbox[3] - r2.bbox[1])
    unionArea = area1 + area2 - intersectionArea
    overlapArea = intersectionArea*1.0/unionArea  # This should be greater than 0.5 to consider it as a valid detection.
    return overlapArea



# FINAL CSV LOADING -----------------------------------------------------------------

INTERSECTION_AREA_TH = 0.1  # intersection/union to be considered matched region
PREDICTION_TH = 0.8  # prediction threshold

## Generate features, score for each BB and store them
tp, tp_ni, fp, fn, eval_candidates, total_rois = 0, 0, 0, 0, 0, 0
real, pred = [], []  # for auc predictions
for idx, filename in enumerate(file_list):  # to extract form .csv
    if idx>50:
        break

    #filename = "luna_126631670596873065041988320084.npz"
    print "Patient %s (%d/%d)" % (filename, idx, len(file_list))

    if filename not in filenames_scored:
        if filename not in filenames_scored_full:
            print "++ Patient not scored"
            continue
        else:
            print "++ Patient with no acceptable candidates"

    # load patient
    patient = np.load(DATA_PATH + filename)['arr_0']
    if patient.shape[0]!=3:  # skip labels without ground truth
        print "++ Patient without ground truth"
        continue

    # candidate is going to be evaluated
    eval_candidates +=1

    # slices with nodules
    slices = []
    for nslice in range(patient.shape[1]):
        if patient[2,nslice].any()!=0:
            slices.append(nslice)


    for idx, row in df_node[df_node['filename']==filename].iterrows():
        # row = df_node[(df_node['filename']==filename)].iloc[300]
        cx = int(row['x'])  # row
        cy = int(row['y'])  # column
        z = int(row['nslice'])
        score = float(row['score'])
        r = int(ceil(row['diameter']/2.))

        # Get the ground truth regions
        if np.sum(patient[2,z])!=0:
            regions = extract_regions_from_heatmap(patient[2,z])
        else:  # if no nodules, skip row and count as FP
            if score > PREDICTION_TH:
                fp+=1
            # auc
            real.append(0)
            pred.append(score)
            continue

        if len(regions)>1:
            print 'Patient: %s has more than 1 region at slice %d' % (filename, z)
        a = AuxRegion([cx - r, cy - r, cx + r + 1, cy + r + 1])  # x1, y1, x2, y2
        intersection_area = intersection_regions(a,regions[0])

        # auc
        real.append(int(intersection_area >= INTERSECTION_AREA_TH))
        pred.append(score)

        # confusion matrix
        if intersection_area >= INTERSECTION_AREA_TH:
            if score > PREDICTION_TH:
                tp+=1
            else:
                tp_ni+=1  # roi candidates not identified by DL network
            if z in slices:
                slices.remove(z)
        elif intersection_area < INTERSECTION_AREA_TH and score > PREDICTION_TH:
            fp+=1

    fn += len(slices)
    num_rois = len(df_node[df_node['filename']==filename].index)
    total_rois += num_rois
    print "Results TP:%d, TPNI:%d, FP:%d FN:%d of %d ROIs candidates" % (tp,tp_ni,fp,fn,num_rois)

print "Results TP:%d, TPNI:%d, FP:%d FN:%d for %d patients evaluated with %d patches" % (tp,tp_ni,fp,fn,eval_candidates,total_rois)
print "AUC: %.4f" % metrics.auc(real,pred,reorder=True)