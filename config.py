colors_dict = {
    "Green1": [65, 255, 28],
    "Yellow": [255, 160, 8],
    "Purple": [185, 63, 255],
    "Red": [255, 11, 11],
    "Blue1": [83, 255, 129],
    "Pink": [255, 129, 129],
    "Green2": [0, 255, 6],
    "Blue2": [16, 73, 255],
}

# analyzer paramters
sr = 44100
delay_seconds = 0.2
history_s = 0.5
hop_length = 512
frame_length = 2048

# change this to accomadate the audio monitor
# analyze time (~0.02s) ~= hops_per_analyse * time_interval (hop_length / sr ~ 0.01s)
hops_per_analyse = 3