from vidgear.gears import CamGear
import cv2
import time

# source="https://youtu.be/BxEmGNapmr4" #philipine
source="https://youtu.be/DLmn7f9SJ5A" # new orleans
# source="https://shiftup.sharepoint.com/:v:/r/sites/E-SWKApplication/Shared%20Documents/E-SWK/SX-APP/projects/SX_MON_HC2_HC2-F24G_2024-12-12_10-48-18_P656700/SX_MON_HC2_HC2-F24G_REF.mp4?csf=1&web=1&e=hBZCuP"
# source = "https://shiftup.sharepoint.com/:v:/r/sites/E-SWKApplication/Shared%20Documents/E-SWK/SX-APP/projects/SX_MON_HC2_HC2-F24G_2024-12-12_10-48-18_P656700/SX_MON_HC2_HC2-F24G_REF.mp4?csf=1&web=1&e=HXhlJg&nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJTdHJlYW1XZWJBcHAiLCJyZWZlcnJhbFZpZXciOiJTaGFyZURpYWxvZy1MaW5rIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXcifX0%3D"
# Add YouTube Video URL as input source (for e.g https://youtu.be/bvetuLwJIkA)
# and enable Stream Mode (`stream_mode = True`)
stream = CamGear(
    source=source, stream_mode=True, logging=True,  time_delay=0
).start()
video_metadata=stream.ytv_metadata

print(video_metadata.keys())

print(video_metadata['fps'])
print(video_metadata['format'])
print(video_metadata['format_index'])

# search available resolution
resolutions=[format['resolution'] for format in video_metadata['formats']]
for res in resolutions:
    print(res)

# select the desired resolution to get right url 
# desired_resolution = '1280x720'
desired_resolution = '854x480'
for format in video_metadata['formats']:
    
    if format['resolution'] == desired_resolution:
        VIDEO = format['url']
        break

print(VIDEO)
