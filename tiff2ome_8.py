import pandas as pd
import numpy as np
import tifffile
from xml.etree import ElementTree as ET
import os
import tkinter as tk
from tkinter import filedialog, ttk
import threading
# from imagecodecs import lzw_encode

def readtiff(fn):
    tif = tifffile.TiffFile(fn)
    IDstring = {t.name: t.value for t in tif.pages[0].tags}['ImageDescription']
    m_ls = [v.split("\"")[0] for v in IDstring.split('<channels>')[1].split('</channels>')[0].split("name=\"")][1:]
    page_df = pd.DataFrame([v.split("\"") for v in IDstring.split('<pixels>')[1].split('</pixels>')[0].split("\n")[1:]])
    page_df = page_df.loc[page_df[6] == ' channel=', [5, 7, 9]].astype(int)
    page_df.columns = ['page', 'channel', 'level']
    page_df = page_df.sort_values(['channel', 'level'])
    page_df['channel'] = np.array(m_ls)[page_df['channel']]
    return tif, page_df

def create_ome_metadata(page_df, pixel_type, sizes):
    physical_size = 0.5
    root = ET.Element('OME', xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06")
    max_level = page_df['level'].max()
    image = ET.SubElement(root, 'Image', ID="Image:0", Name="Multipage Image")
    pixels = ET.SubElement(image, 'Pixels',
                           ID="Pixels:0",
                           DimensionOrder="XYCZT",
                           Type=pixel_type,
                           SizeX=str(sizes[1]),
                           SizeY=str(sizes[0]),
                           SizeC=str(len(page_df['channel'].unique())),
                           SizeZ="1",
                           SizeT="1",
                           Interleaved="false",
                           PhysicalSizeX=str(physical_size),
                           PhysicalSizeY=str(physical_size))
    for idx, channel in enumerate(page_df['channel'].unique()):
        ET.SubElement(pixels, 'Channel', ID=f"Channel:0:{idx}", Name=channel, SamplesPerPixel="1")
        ET.SubElement(pixels, 'TiffData', IFD=str(idx * (max_level + 1)), PlaneCount=str(max_level + 1))
    return ET.tostring(root, encoding='ascii', method='xml').decode('ascii')

def create_pyramidal_ome_tiff(fn, progress, status_label, start_button, browse_button):
    output_path = fn + '.lossless.ome.tiff'
    tif, page_df  = readtiff(fn)
    try:
        sizes = tif.pages[0].asarray().shape
        # pixel_type = tif.pages[0].asarray().dtype

        original_dtype = tif.pages[0].dtype
        pixel_type_map = {
            np.dtype('uint8'): 'uint8',
            np.dtype('uint16'): 'uint16',
            np.dtype('float32'): 'float',
            np.dtype('float64'): 'double'
        }
        pixel_type = pixel_type_map.get(original_dtype, 'uint8')  # Default to 'uint8' if type is not in the map

        metadata = create_ome_metadata(page_df, pixel_type, sizes)
        max_level = page_df['level'].max()
        progress["maximum"] = len(page_df['channel'].unique()) * (max_level + 1)
        with tifffile.TiffWriter(output_path, bigtiff=True) as tiff:
            for channel_idx, channel in enumerate(page_df['channel'].unique()):
                for level in range(max_level + 1):
                    row = page_df[(page_df['channel'] == channel) & (page_df['level'] == level)].iloc[0]
                    img_array = tif.pages[row['page']].asarray()
                    if level == 0:
                        tiff.write(
                            img_array,
                            photometric='minisblack',
                            tile=(256, 256),
                            compression=8,  # Use JPEG compression
                            # compressionargs={'jpeg': {'lossless': True}},
                            extratags=[(285, 's', 0, channel, True)],
                            subifds=max_level,
                            description=metadata if channel_idx == 0 and level == 0 else None
                        )
                    else:
                        status_label.config(text=f'Processing... ({int(progress["value"])}/{progress["maximum"]})')
                        tiff.write(
                            img_array,
                            photometric='minisblack',
                            tile=(256, 256),
                            compression = 8,
                            # compression='jpeg',  # Use JPEG compression
                            # compressionargs={'jpeg': {'lossless': True}},
                            subfiletype=1
                        )
                    progress["value"] += 1
                    progress.update()
        status_label.config(text='Done!')
    except Exception as e:
        status_label.config(text=f'Error: {str(e)}')
    finally:
        start_button.config(state=tk.NORMAL)
        browse_button.config(state=tk.NORMAL)

def start_task(file_path, progress, status_label, start_button, browse_button):
    status_label.config(text='Initializing...')
    start_button.config(state=tk.DISABLED)
    browse_button.config(state=tk.DISABLED)
    threading.Thread(target=create_pyramidal_ome_tiff, args=(file_path, progress, status_label, start_button, browse_button)).start()

def open_file_dialog(entry, initialdir):
    file_path = filedialog.askopenfilename(initialdir=initialdir)
    entry.delete(0, tk.END)
    entry.insert(0, file_path)

def create_gui():
    window = tk.Tk()
    window.title("HALO Tiff to OME")

    style = ttk.Style()
    style.configure('TButton', font=('Helvetica', 12))
    style.map('TButton',
              foreground=[('active', 'black'), ('disabled', 'grey')],
              background=[('active', 'lightgrey'), ('disabled', 'lightgrey')],
              relief=[('pressed', 'sunken'), ('!pressed', 'raised')],
              bordercolor=[('active', 'black'), ('disabled', 'grey')],
              highlightcolor=[('focus', 'black'), ('!focus', 'white')])
    
    frame = ttk.Frame(window, padding=10)
    frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    file_path_label = ttk.Label(frame, text="File Path:")
    file_path_label.grid(row=0, column=0, sticky=tk.W)

    file_path_entry = ttk.Entry(frame, width=50)
    file_path_entry.grid(row=0, column=1, padx=5, pady=5)
    file_path_entry.insert(0, os.curdir)  # Set your default directory here

    browse_button = ttk.Button(frame, text="Browse", style='TButton', 
                               command=lambda: open_file_dialog(file_path_entry, "/path/to/your/default/directory"))
    browse_button.grid(row=0, column=2, padx=5, pady=5)

    progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=300, mode='determinate')
    progress.grid(row=2, column=0, columnspan=3, padx=5, pady=5)

    status_label = ttk.Label(frame, text="Status: Idle")
    status_label.grid(row=3, column=0, columnspan=3, pady=5)

    start_button = ttk.Button(frame, text="Start", style='TButton',
                              command=lambda: start_task(file_path_entry.get(), progress, status_label, start_button, browse_button))
    start_button.grid(row=1, column=1, padx=5, pady=5)

    window.mainloop()

if __name__ == '__main__':
    create_gui()
