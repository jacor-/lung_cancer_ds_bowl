import numpy as np
import pandas as pd
import dicom
import os
import scipy.ndimage
import matplotlib.pyplot as plt
import SimpleITK as sitk
import operator

from skimage import measure, morphology
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def ball(rad, center, spatialScaling = [1, 1, 1]):
    """
    Creates a ball of radius R, centered in the coordinates center
    @param R: radius of the ball, in mm 
    @param center: center of the ball (slice, x, y) in pixel coordinates

    @spatialSpacing

    returns a list of coordinates (x, y, z) that are in the ball of radius r centered in 0.
    """

    # Generate the mesh of candidates
    r = np.ceil(rad / spatialScaling).astype(int) # anisotropic spacing
    x, y, z = np.meshgrid(xrange(-r[0], r[0] + 1), xrange(-r[1], r[1] + 1), xrange(-r[2], r[2] + 1))
    mask = (x*spatialScaling[0])**2 + (y * spatialScaling[1])**2 + (z * spatialScaling[2])**2 <= rad**2
    return np.stack((x[mask] + center[0], y[mask] + center[1], z[mask] + center[2])).T


def draw_in_mask(mask, pointCoordinates):
    """
    Draws the coordinates in the mask
    """
    for p in pointCoordinates:
        mask[p[0], p[1], p[2]] = 1
    return mask


def list_final_subfolders(path, max_depth = 10):
    """
    recursively list all subfolders that do not have.
    WARNING: not cyclic folders, please!
    """
    if max_depth == 0:
        raise Exception('Error reading %s, reached maximal recursion level')
    
    files = [os.path.join(path, o) for o in os.listdir(path) if os.path.isdir(os.path.join(path, o))]
    if files:
        return reduce(operator.__add__, (list_final_subfolders(f, max_depth - 1) for f in files), [])
    else:
        return [path]


def read_nodules_lidc(nodules, pat_id_num, series_num, spacing):
    """
    Reads the nodule list from the csv and returns a list of ((px_coordinates), diameter (mm))
    """

    nodules_pat = nodules[(nodules['case'] == pat_id_num)]
    res = []
    for i in xrange(len(nodules_pat)):
        if nodules_pat['scan'].iloc[i] == series_num:
            px_coordinates = np.array([nodules_pat['slice no.'].iloc[i], nodules_pat['x loc.'].iloc[i],
                                       nodules_pat['y loc.'].iloc[i]], dtype = np.int16)
            d = nodules_pat['eq. diam.'].iloc[i]
            res.append((px_coordinates, d))
    return res
    

def read_patient_lidc(path):
    """
    @param path: path of the patients DCOMS

    Reads a patient that has potentially more than one DICOM study (not always CT).
    Gives warning and discards one,  if two CT explorations are found.
    Some patient have only radiography, so they are discarded as well.
    """
    
    # 1st, obtain all the folders.
    possible_patients_folders = list_final_subfolders(path)
    patient_ct_explorations = []
    for p in possible_patients_folders:
        dcms = load_scan(p)
        if dcms:
            patient_ct_explorations.append(dcms)
                   
    # Check if there is more than one dcms,
    if not patient_ct_explorations:
        raise Exception('No CT exploration found - (normal in LIDC)')
    elif len(patient_ct_explorations) > 1:
        print("Warning: more than one CT exploration found. Discarding all but the first one.")
        
    patient_data = patient_ct_explorations[0]
    return patient_data


def dicom_get_thickness(slices):
    """
    Gets the slice thickness. It might be in either slice thickness or location
    """
    try:
        return np.abs(slices[0].ImagePositionPatient[2] - slices[1].ImagePositionPatient[2])
    except:
        pass
    try:
        return np.abs(slices[0].SliceLocation - slices[1].SliceLocation)
    except:
        return slices[0].SliceThickness


def dicom_get_spacing(slices):
    """
    Gets the spacing in the DCM
    """
    return map(float, ([slices[0].SliceThickness] + slices[0].PixelSpacing))


def load_scan(patient_path):
    """
    Given a patient path, returns an array of scans from the DICOM files. Check that the files are dicoms, and the
    modality is CT.
    """
    slices = filter(lambda s: s.endswith('.dcm'), os.listdir(patient_path))
    slices = [dicom.read_file(os.path.join(patient_path, s)) for s in slices]
    
    # Check that the modality is CT
    if not slices or slices[0].Modality != 'CT':
        return []
    slices.sort(key=lambda x: int(x.InstanceNumber))
    try:
        slice_thickness = np.abs(slices[0].ImagePositionPatient[2] - slices[1].ImagePositionPatient[2])
    except:
        slice_thickness = np.abs(slices[0].SliceLocation - slices[1].SliceLocation)
        
    for s in slices:
        s.SliceThickness = slice_thickness

    return slices

    
def scan2imgs(scans):
    """Convert scans to array of pixel images."""
    imgs = np.stack([s.pixel_array for s in scans])
    imgs = imgs.astype(np.int16)
    imgs = np.array(imgs, dtype=np.int16)
    return imgs


def load_slices_from_mhd(img_file):
    itk_img = sitk.ReadImage(img_file)
    img_array = sitk.GetArrayFromImage(itk_img)  # indexes are z,y,x
    return img_array
    

def make_mask(center, diam, z, width, height, spacing, origin):
    """
    Center : centers of circles px -- list of coordinates x,y,z
    diam : diameters of circles px -- diameter
    widthXheight : pixel dim of image
    spacing = mm/px conversion rate np array x,y,z
    origin = x,y,z mm np.array
    z = z position of slice in world coordinates mm
    """
    mask = np.zeros([height, width], dtype=np.uint8)  # 0's everywhere except nodule swapping x,y to match img
    # convert to nodule space from world coordinates

    # Defining the voxel range in which the nodule falls
    v_center = (center-origin)/spacing
    v_diam = int(diam/spacing[0]+5)
    v_xmin = np.max([0, int(v_center[0]-v_diam)-5])
    v_xmax = np.min([width-1, int(v_center[0]+v_diam)+5])
    v_ymin = np.max([0, int(v_center[1]-v_diam)-5])
    v_ymax = np.min([height-1, int(v_center[1]+v_diam)+5])

    v_xrange = range(v_xmin, v_xmax+1)
    v_yrange = range(v_ymin, v_ymax+1)

    # Fill in 1 within sphere around nodule
    for v_x in v_xrange:
        for v_y in v_yrange:
            p_x = spacing[0]*v_x + origin[0]
            p_y = spacing[1]*v_y + origin[1]
            if np.linalg.norm(center-np.array([p_x,p_y,z]))<=diam:
                mask[int((p_y-origin[1])/spacing[1]),int((p_x-origin[0])/spacing[0])] = 1
    return mask


def create_mask(img, nodules):

    if len(nodules) == 0:
        return None

    height, width, num_z = img.GetSize()
    masks = np.zeros([num_z, height, width], dtype=np.uint8)
    origin = np.array(img.GetOrigin())  # x,y,z  Origin in world coordinates (mm)
    spacing = np.array(img.GetSpacing())  # spacing of voxels in world coor. (mm)

    for index, row in nodules.iterrows():
        node_x = row["coordX"]
        node_y = row["coordY"]
        node_z = row["coordZ"]
        diam = row["diameter_mm"]
        center = np.array([node_x, node_y, node_z])  # nodule center
        v_center = np.rint((center-origin)/spacing)  # nodule center in voxel space

        for i_z in range(int(v_center[2])-1,int(v_center[2])+2):
            new_mask = make_mask(center, diam, i_z*spacing[2] + origin[2], width, height, spacing, origin)
            masks[i_z, :, :] = np.bitwise_or(masks[i_z, :, :], new_mask)

    return masks

