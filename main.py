# maritime-router v12 — Graph-Based Routing Engine
# Built from 26 real PortToPort RTZ routes → 1034 nodes, 1063 edges
# Accuracy: ~0.6–6% of PortToPort distances (same waypoint logic)
#
# Architecture:
#   1. Every route query finds nearest graph nodes to origin/destination
#   2. A* search through the PortToPort-derived waypoint graph
#   3. No searoute needed for the path — graph IS the routing network
#   4. searoute used only as fallback when graph path not found
#   5. TSS/ECA/Piracy zones already encoded as named graph nodes
#
# Endpoints: GET /route  POST /safety-check  GET /health  GET /graph/stats

import os, sys, math, heapq, threading, json, requests
from flask import Flask, request, jsonify
from shapely.geometry import LineString
import geopandas as gpd

app = Flask(__name__)

@app.after_request
def add_cors(r):
    r.headers['Access-Control-Allow-Origin']  = '*'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return r

# ══════════════════════════════════════════════════════════════
# ROUTING GRAPH — 1034 nodes, 1063 edges
# Extracted from 26 PortToPort RTZ routes covering:
#   Europe ↔ Asia (Suez), Americas ↔ Europe (Atlantic),
#   Pacific routes, Indian Ocean, Mediterranean, Baltic,
#   Black Sea, Persian Gulf, Red Sea, Malacca, Singapore Strait
# ══════════════════════════════════════════════════════════════
_GRAPH_NODES = [[0, 'Antwerp', 51.346667, 4.27, 'named_waypoint'], [1, 'Antwerp - Noordzee Container Terminal', 51.350333, 4.2575, 'named_waypoint'], [2, '', 51.359333, 4.227067, 'waypoint'], [3, '', 51.393667, 4.209117, 'waypoint'], [4, '', 51.373967, 4.144067, 'waypoint'], [5, '', 51.370033, 4.08325, 'waypoint'], [6, '', 51.38735, 4.036883, 'waypoint'], [7, '', 51.421667, 4.028617, 'waypoint'], [8, '', 51.433433, 3.977767, 'waypoint'], [9, '', 51.385483, 3.9486, 'waypoint'], [10, '', 51.353583, 3.886733, 'waypoint'], [11, '', 51.346533, 3.81305, 'waypoint'], [12, '', 51.37205, 3.734067, 'waypoint'], [13, '', 51.408333, 3.708833, 'waypoint'], [14, '', 51.439217, 3.67285, 'waypoint'], [15, '', 51.433383, 3.607033, 'waypoint'], [16, '', 51.420733, 3.506217, 'waypoint'], [17, '', 51.40565, 3.35855, 'waypoint'], [18, '', 51.4105, 3.249567, 'waypoint'], [19, '', 51.4035, 3.173967, 'waypoint'], [20, '', 51.399083, 3.098383, 'waypoint'], [21, '', 51.414019, 2.965475, 'waypoint'], [22, '', 51.423282, 2.875114, 'waypoint'], [23, '', 51.424903, 2.811619, 'waypoint'], [24, 'Wandelaar Pilots', 51.383333, 2.711667, 'pilot_station'], [25, '', 51.383333, 2.491667, 'waypoint'], [26, '', 51.34, 2.291667, 'waypoint'], [27, '', 51.355, 2.186667, 'waypoint'], [28, '', 51.403333, 2.14, 'waypoint'], [29, '', 51.808333, 2.683333, 'waypoint'], [30, '', 52.218333, 2.71, 'waypoint'], [31, '', 52.501484, 2.966918, 'waypoint'], [32, '', 52.80776, 3.246704, 'waypoint'], [33, '', 52.916667, 3.346667, 'waypoint'], [34, '', 53.153323, 3.512826, 'waypoint'], [35, '', 53.51, 3.765, 'waypoint'], [36, '', 53.78, 4.388333, 'waypoint'], [37, '', 53.921, 4.599633, 'waypoint'], [38, '', 54.066667, 4.671667, 'waypoint'], [39, '', 54.238333, 4.74, 'waypoint'], [40, '', 55.433333, 5.575, 'waypoint'], [41, '', 56.841667, 5.776667, 'waypoint'], [42, '', 57.901667, 9.941667, 'waypoint'], [43, 'Skaw', 57.901667, 10.618333, 'headland'], [44, "Route T to Skaw S'bound", 57.829783, 10.691533, 'headland'], [45, "Route T to Skaw N'bound", 57.795972, 10.73123, 'waypoint'], [46, 'Exit North Sea zone, Exit Special Areas - Garbage zone, Enter Baltic zone, Enter Special Areas - Garbage and Chemicals zone', 57.746667, 10.830748, 'zone_boundary'], [47, '', 57.461667, 11.403333, 'waypoint'], [48, '', 57.089003, 11.649967, 'waypoint'], [49, '', 56.922607, 11.759266, 'waypoint'], [50, '', 56.858013, 11.801582, 'waypoint'], [51, '', 56.753333, 11.87, 'waypoint'], [52, '', 56.293333, 12.066667, 'waypoint'], [53, '', 56.231667, 12.223333, 'waypoint'], [54, '', 56.116667, 12.508333, 'waypoint'], [55, 'The Sound(Helsingor) - S bound', 56.053333, 12.641667, 'strait'], [56, '', 55.981667, 12.678333, 'waypoint'], [57, '', 55.91, 12.741667, 'waypoint'], [58, '', 55.853333, 12.746667, 'waypoint'], [59, '', 55.813333, 12.733333, 'waypoint'], [60, '', 55.738333, 12.688333, 'waypoint'], [61, '', 55.691667, 12.683333, 'waypoint'], [62, '', 55.55, 12.706667, 'waypoint'], [63, '', 55.418333, 12.655, 'waypoint'], [64, '', 55.32, 12.625, 'waypoint'], [65, '', 55.281667, 12.693333, 'waypoint'], [66, '', 55.248333, 12.858333, 'waypoint'], [67, '', 55.16, 14.303333, 'waypoint'], [68, '', 55.42, 14.678333, 'waypoint'], [69, '', 55.42, 15.206667, 'waypoint'], [70, '', 55.108333, 18.225, 'waypoint'], [71, '', 55.00445, 18.590367, 'waypoint'], [72, '', 54.748333, 18.961667, 'waypoint'], [73, '', 54.67, 18.94, 'waypoint'], [74, '', 54.588333, 18.875, 'waypoint'], [75, '', 54.536667, 18.796667, 'waypoint'], [76, 'Pilots', 54.476667, 18.706667, 'waypoint'], [77, '', 54.447933, 18.674183, 'waypoint'], [78, '', 54.415733, 18.657483, 'waypoint'], [79, 'Gdansk', 54.381667, 18.658333, 'named_waypoint'], [80, 'Busan', 35.108333, 129.058333, 'named_waypoint'], [81, '', 35.078333, 129.111667, 'waypoint'], [82, '', 35.022117, 129.163633, 'waypoint'], [83, 'Exit Republic of Korea zone', 34.965243, 129.132279, 'zone_boundary'], [84, '', 34.621667, 128.943333, 'waypoint'], [85, '', 25.836667, 123.848333, 'waypoint'], [86, '', 24.505, 122.828333, 'waypoint'], [87, '', 22.6, 121.666667, 'waypoint'], [88, '', 22.18875, 121.339742, 'waypoint'], [89, '', 21.668333, 120.983333, 'waypoint'], [90, '', 7.64, 108.71, 'waypoint'], [91, '', 7.188399, 108.340075, 'waypoint'], [92, '', 4.266667, 105.95, 'waypoint'], [93, '', 2.64, 105.11, 'waypoint'], [94, '', 1.5, 104.543333, 'waypoint'], [95, '', 1.416667, 104.443333, 'waypoint'], [96, 'Singapore East(Horsborough) W bound', 1.316667, 104.326667, 'named_waypoint'], [97, '', 1.293333, 104.203333, 'waypoint'], [98, '', 1.278333, 104.109167, 'waypoint'], [99, '', 1.261667, 104.0, 'waypoint'], [100, '', 1.231667, 103.918333, 'waypoint'], [101, '', 1.215, 103.886667, 'waypoint'], [102, 'Southern Boarding Ground - Singapore', 1.198333, 103.855, 'waypoint'], [103, '', 1.171667, 103.791667, 'waypoint'], [104, '', 1.136667, 103.736667, 'waypoint'], [105, 'Western Boarding Ground B - Singapore', 1.181667, 103.665, 'waypoint'], [106, 'Western Boarding Ground A - Singapore', 1.191172, 103.609173, 'waypoint'], [107, '', 1.210833, 103.521667, 'waypoint'], [108, 'Singapore West(The Brothers) - NW Bound', 1.241667, 103.411667, 'named_waypoint'], [109, '', 1.411667, 103.18, 'waypoint'], [110, '', 1.458228, 103.114732, 'waypoint'], [111, '', 1.67, 102.818333, 'waypoint'], [112, '', 1.941667, 102.27, 'waypoint'], [113, '', 2.11, 102.091667, 'waypoint'], [114, '', 2.168995, 102.019814, 'waypoint'], [115, '', 2.423333, 101.71, 'waypoint'], [116, '', 2.618333, 101.448333, 'waypoint'], [117, '', 2.831667, 101.0, 'waypoint'], [118, '', 2.903333, 100.931667, 'waypoint'], [119, '', 2.945, 100.91, 'waypoint'], [120, '', 3.031667, 100.801667, 'waypoint'], [121, '', 3.644952, 100.060427, 'waypoint'], [122, '', 3.968333, 99.626667, 'waypoint'], [123, '', 5.393333, 97.625, 'waypoint'], [124, '', 6.273399, 95.174416, 'waypoint'], [125, 'Rondo - Northern Entrance To The Malacca Strait', 6.3, 95.1, 'strait'], [126, '', 5.808333, 80.685, 'waypoint'], [127, 'Dondra Head - W bound', 5.808333, 80.591667, 'named_waypoint'], [128, '', 5.808333, 80.5, 'waypoint'], [129, '', 5.841667, 80.101667, 'waypoint'], [130, '', 7.916667, 77.166667, 'waypoint'], [131, '', 8.593099, 76.444184, 'waypoint'], [132, '', 16.436583, 71.80185, 'waypoint'], [133, '', 18.0037, 70.64775, 'waypoint'], [134, '', 21.613333, 69.005, 'waypoint'], [135, '', 22.306667, 68.760003, 'waypoint'], [136, '', 22.345, 68.816667, 'waypoint'], [137, '', 22.48538, 68.879284, 'waypoint'], [138, '', 22.578333, 68.923333, 'waypoint'], [139, '', 22.611667, 68.958333, 'waypoint'], [140, '', 22.638333, 69.016667, 'waypoint'], [141, '', 22.638333, 69.158333, 'waypoint'], [142, '', 22.621667, 69.2, 'waypoint'], [143, '', 22.583333, 69.271667, 'waypoint'], [144, '', 22.583333, 69.316667, 'waypoint'], [145, '', 22.63, 69.46, 'waypoint'], [146, 'Offshore Sikka (Tsa)', 22.633333, 69.533333, 'named_waypoint'], [147, '', 22.628333, 69.625, 'waypoint'], [148, '', 22.666667, 69.705, 'waypoint'], [149, 'Pilots', 22.703332, 69.701859, 'pilot_station'], [150, '', 7.303333, 72.928333, 'waypoint'], [151, 'Enter Piracy zone', 13.111884, 60.0, 'zone_boundary'], [152, 'Enter Special Areas - Oil - Oman area of the Arabian Sea zone', 14.26119, 57.206214, 'zone_boundary'], [153, '', 15.033333, 55.266667, 'waypoint'], [154, '', 15.033333, 54.916667, 'waypoint'], [155, 'Exit Special Areas - Oil - Oman area of the Arabian Sea zone', 14.794847, 54.121088, 'zone_boundary'], [156, 'Gulf of Aden Transit Corridor - West Bound Entrance', 14.458333, 53.0, 'corridor'], [157, 'Enter Special Areas - Oil and Garbage zone', 14.099325, 51.84167, 'zone_boundary'], [158, '', 13.704986, 50.57147, 'waypoint'], [159, '', 13.336667, 49.386667, 'waypoint'], [160, '', 13.106019, 48.646201, 'waypoint'], [161, '', 13.001286, 48.317336, 'waypoint'], [162, 'Gulf of Aden Transit Corridor - West Bound Exit', 11.958333, 45.0, 'zone_boundary'], [163, '', 12.565, 43.47, 'waypoint'], [164, 'Exit Special Areas - Oil and Garbage zone, Enter Special Areas - Garbage zone', 12.588696, 43.424092, 'zone_boundary'], [165, 'Red Sea Southern - N bound', 12.618333, 43.366667, 'named_waypoint'], [166, '', 13.24, 43.07, 'waypoint'], [167, '', 13.496167, 42.745083, 'waypoint'], [168, '', 13.561883, 42.659183, 'waypoint'], [169, '', 13.677917, 42.605667, 'waypoint'], [170, '', 14.893533, 41.87505, 'waypoint'], [171, 'Exit Piracy zone', 15.0, 41.832659, 'zone_boundary'], [172, '', 15.47935, 41.641533, 'waypoint'], [173, '', 17.001667, 40.773333, 'waypoint'], [174, '', 21.008696, 38.386542, 'waypoint'], [175, '', 24.981667, 35.955, 'waypoint'], [176, '', 26.35, 34.935, 'waypoint'], [177, '', 27.533333, 34.121667, 'waypoint'], [178, '', 27.746667, 33.836667, 'waypoint'], [179, '', 27.851667, 33.743333, 'waypoint'], [180, '', 27.933333, 33.631667, 'waypoint'], [181, '', 28.171667, 33.355, 'waypoint'], [182, '', 28.601667, 33.056667, 'waypoint'], [183, '', 29.175, 32.776667, 'waypoint'], [184, '', 29.476667, 32.628333, 'waypoint'], [185, '', 29.591667, 32.571667, 'waypoint'], [186, '', 29.788333, 32.546667, 'waypoint'], [187, 'Suez Canal - Suez Exit', 29.835, 32.553333, 'canal'], [188, '', 29.90915, 32.545767, 'waypoint'], [189, '', 29.938583, 32.570533, 'waypoint'], [190, '', 29.9802, 32.585917, 'waypoint'], [191, '', 30.061083, 32.571283, 'waypoint'], [192, '', 30.187567, 32.568283, 'waypoint'], [193, '', 30.243417, 32.53825, 'waypoint'], [194, '', 30.268833, 32.48245, 'waypoint'], [195, '', 30.294467, 32.430917, 'waypoint'], [196, '', 30.358167, 32.374117, 'waypoint'], [197, '', 30.430183, 32.359233, 'waypoint'], [198, '', 30.509783, 32.337983, 'waypoint'], [199, 'Ismailia - Suez Canal Transit', 30.5486, 32.309433, 'waypoint'], [200, '', 30.582383, 32.305917, 'waypoint'], [201, '', 30.614733, 32.322817, 'waypoint'], [202, '', 30.7032, 32.34345, 'waypoint'], [203, '', 30.805633, 32.317483, 'waypoint'], [204, '', 31.0987, 32.3076, 'waypoint'], [205, 'Port Said - Canal Entrance', 31.42, 32.401667, 'canal'], [206, '', 31.54, 32.228333, 'waypoint'], [207, '', 31.801667, 31.923333, 'waypoint'], [208, 'Cape Passero', 36.183333, 14.883333, 'headland'], [209, '', 36.42533, 14.083807, 'waypoint'], [210, '', 37.04, 12.03, 'waypoint'], [211, '', 37.385, 11.338333, 'waypoint'], [212, '', 37.458333, 11.183333, 'waypoint'], [213, '', 37.65, 10.22, 'waypoint'], [214, '', 37.65, 10.041667, 'waypoint'], [215, '', 37.275, 8.573333, 'waypoint'], [216, '', 37.263214, 7.048157, 'waypoint'], [217, '', 37.257119, 6.37145, 'waypoint'], [218, '', 37.0, 3.0, 'waypoint'], [219, '', 36.438333, -2.188333, 'waypoint'], [220, '', 36.006233, -5.4266, 'waypoint'], [221, '', 35.985, -5.498333, 'waypoint'], [222, '', 35.9718, -5.543033, 'waypoint'], [223, 'Exit Special Areas - Garbage zone', 35.954935, -5.6, 'zone_boundary'], [224, '', 35.95, -6.025, 'waypoint'], [225, '', 35.95, -6.2, 'waypoint'], [226, '', 36.588333, -8.805, 'waypoint'], [227, '', 36.636667, -9.015, 'waypoint'], [228, '', 36.683333, -9.203333, 'waypoint'], [229, '', 36.851667, -9.4, 'waypoint'], [230, '', 36.993333, -9.45, 'waypoint'], [231, '', 37.075, -9.48, 'waypoint'], [232, '', 38.546667, -9.885, 'waypoint'], [233, '', 38.616667, -9.91, 'waypoint'], [234, '', 38.708333, -9.938333, 'waypoint'], [235, '', 38.866667, -9.938333, 'waypoint'], [236, '', 39.0, -9.938333, 'waypoint'], [237, '', 42.716667, -9.95, 'waypoint'], [238, 'Finisterre - N bound', 42.883333, -9.95, 'headland'], [239, '', 43.241667, -9.95, 'waypoint'], [240, '', 43.428333, -9.805, 'waypoint'], [241, '', 43.576667, -9.691667, 'waypoint'], [242, 'Enter Special Areas - Oil and Garbage zone', 48.45, -5.887124, 'zone_boundary'], [243, 'Ushant - NE bound', 48.78, -5.616667, 'headland'], [244, '', 48.961667, -5.146667, 'waypoint'], [245, 'Exit Special Areas - Oil and Garbage zone, Enter North Sea zone, Enter Special Areas - Garbage zone', 49.017445, -5.0, 'zone_boundary'], [246, '', 49.826667, -2.853333, 'waypoint'], [247, '', 49.912046, -2.376078, 'waypoint'], [248, '', 50.250273, -0.477109, 'waypoint'], [249, '', 50.511667, 1.0, 'waypoint'], [250, '', 50.708333, 1.35, 'waypoint'], [251, '', 50.911667, 1.453333, 'waypoint'], [252, 'Dover - NE bound', 50.966667, 1.518333, 'headland'], [253, '', 51.11779, 1.757655, 'waypoint'], [254, '', 51.143333, 1.798333, 'waypoint'], [255, '', 51.233333, 2.078333, 'waypoint'], [256, '', 51.313333, 2.133333, 'waypoint'], [257, '', 51.838608, 2.904971, 'waypoint'], [258, '', 51.8678, 3.088417, 'waypoint'], [259, '', 51.90265, 3.299683, 'waypoint'], [260, '', 51.9183, 3.389, 'waypoint'], [261, '', 51.983593, 3.783148, 'waypoint'], [262, 'Maas Center Pilots', 52.011667, 3.893333, 'waypoint'], [263, '', 51.9926, 4.036367, 'waypoint'], [264, 'Hook of Holland', 51.9802, 4.10225, 'waypoint'], [265, '', 51.95075, 4.170317, 'waypoint'], [266, 'Maassluis', 51.930667, 4.220333, 'waypoint'], [267, '', 51.90315, 4.271133, 'waypoint'], [268, '', 51.893467, 4.327917, 'waypoint'], [269, 'Rotterdam', 51.897017, 4.385433, 'waypoint'], [270, 'Exit Republic of Korea zone', 34.992149, 129.21561, 'zone_boundary'], [271, '', 34.775, 129.591667, 'waypoint'], [272, '', 34.061667, 130.785, 'waypoint'], [273, '', 33.99, 130.881667, 'waypoint'], [274, '', 33.956667, 130.866667, 'waypoint'], [275, 'Kanmon Kaikyo ( W. Entrance To Inland Sea)', 33.905017, 130.899267, 'waypoint'], [276, '', 33.930839, 130.934918, 'waypoint'], [277, '', 33.964517, 130.95945, 'waypoint'], [278, '', 33.976683, 130.997183, 'waypoint'], [279, '', 33.963917, 131.034617, 'waypoint'], [280, '', 33.86, 131.196667, 'waypoint'], [281, '', 33.841267, 131.291573, 'waypoint'], [282, '', 33.77, 131.706667, 'waypoint'], [283, '', 33.550126, 131.838009, 'waypoint'], [284, '', 33.520299, 131.857351, 'waypoint'], [285, '', 33.368032, 131.955666, 'waypoint'], [286, 'Bungo- S.W. Entrance Japanese Inland Sea', 33.301667, 131.996667, 'named_waypoint'], [287, '', 33.021667, 132.138333, 'waypoint'], [288, '', 32.675, 132.391667, 'waypoint'], [289, '', 32.613333, 133.036667, 'waypoint'], [290, '', 33.283333, 135.763333, 'waypoint'], [291, '', 34.413333, 138.845, 'waypoint'], [292, '', 34.42, 138.941667, 'waypoint'], [293, '', 34.458333, 139.023333, 'waypoint'], [294, '', 34.701483, 139.1698, 'waypoint'], [295, '', 34.797867, 139.28635, 'waypoint'], [296, '', 34.831667, 139.323333, 'waypoint'], [297, '', 35.086667, 139.756667, 'waypoint'], [298, 'Pilots', 35.175, 139.78, 'pilot_station'], [299, '', 35.211667, 139.781667, 'waypoint'], [300, '', 35.256667, 139.781667, 'waypoint'], [301, '', 35.316667, 139.73, 'waypoint'], [302, '', 35.355851, 139.710588, 'waypoint'], [303, '', 35.407334, 139.728543, 'waypoint'], [304, 'Yokohama', 35.448333, 139.685, 'named_waypoint'], [305, 'Cape Of Good Hope', -34.7, 18.118333, 'headland'], [306, '', -35.253333, 19.995, 'waypoint'], [307, '', -35.081667, 22.188333, 'waypoint'], [308, '', -34.643333, 24.896667, 'waypoint'], [309, '', -34.36445, 25.84935, 'waypoint'], [310, 'Exit Special Areas - Oil - South Africa zone', -34.055467, 26.90102, 'zone_boundary'], [311, '', -33.935, 27.31, 'waypoint'], [312, '', -25.642942, 47.44162, 'waypoint'], [313, '', -20.670516, 57.992981, 'waypoint'], [314, '', 6.045, 94.725, 'waypoint'], [315, '', 6.250513, 95.006863, 'waypoint'], [316, '', 2.906667, 100.761667, 'waypoint'], [317, '', 2.813333, 100.943333, 'waypoint'], [318, '', 2.58, 101.395, 'waypoint'], [319, '', 2.398333, 101.636667, 'waypoint'], [320, '', 2.135, 101.976667, 'waypoint'], [321, '', 2.087418, 102.029346, 'waypoint'], [322, '', 1.9, 102.236667, 'waypoint'], [323, '', 1.633333, 102.788333, 'waypoint'], [324, 'Singapore West(The Brothers) - SE Bound', 1.211667, 103.378333, 'named_waypoint'], [325, '', 1.174419, 103.425202, 'waypoint'], [326, '', 1.148333, 103.486667, 'waypoint'], [327, '', 1.13, 103.516667, 'waypoint'], [328, 'Singapore - Sinki Fairway', 1.216667, 103.678333, 'waypoint'], [329, '', 1.231667, 103.711667, 'waypoint'], [330, '', 1.243333, 103.743333, 'waypoint'], [331, 'Singapore', 1.249603, 103.78739, 'waypoint'], [332, 'Colombo', 6.95, 79.85, 'named_waypoint'], [333, '', 6.98435, 79.827683, 'waypoint'], [334, 'Colombo Pilots', 7.01455, 79.797717, 'pilot_station'], [335, '', 6.991717, 79.764867, 'waypoint'], [336, '', 6.897867, 79.6777, 'waypoint'], [337, '', 6.764383, 79.7025, 'waypoint'], [338, '', 6.370467, 79.818017, 'waypoint'], [339, '', 5.708333, 80.363333, 'waypoint'], [340, '', -5.663333, 102.106667, 'waypoint'], [341, '', -6.143333, 104.565, 'waypoint'], [342, '', -6.256667, 105.5, 'waypoint'], [343, '', -6.163333, 105.638333, 'waypoint'], [344, '', -6.0, 105.638333, 'waypoint'], [345, 'Sunda Strait', -5.9, 105.808333, 'strait'], [346, '', -5.251667, 106.208333, 'waypoint'], [347, '', -5.286283, 106.4617, 'waypoint'], [348, '', -5.295, 106.783333, 'waypoint'], [349, '', -5.131667, 107.078333, 'waypoint'], [350, '', -5.353559, 109.975848, 'waypoint'], [351, 'ASL - Pulau Bawean', -5.508333, 112.0, 'named_waypoint'], [352, '', -5.861667, 114.32, 'waypoint'], [353, '', -5.735866, 114.601121, 'waypoint'], [354, '', -5.603206, 114.788248, 'waypoint'], [355, '', -4.324326, 115.703332, 'waypoint'], [356, '', -4.047995, 115.925211, 'waypoint'], [357, 'Pilots', -4.017137, 115.982427, 'pilot_station'], [358, 'Indonesia Bulk Terminal (South Pula Laut Coal Terminal)', -4.0, 116.041664, 'named_waypoint'], [359, '', 9.918333, 72.098333, 'waypoint'], [360, '', 14.0004, 60.0263, 'waypoint'], [361, 'Enter Piracy zone', 14.008333, 59.989829, 'zone_boundary'], [362, 'Enter Special Areas - Oil - Oman area of the Arabian Sea zone', 14.476286, 57.836265, 'zone_boundary'], [363, '', 27.902383, 33.669517, 'waypoint'], [364, '', 50.235, -0.571667, 'waypoint'], [365, '', 55.565, 15.016667, 'waypoint'], [366, '', 55.616667, 15.316667, 'waypoint'], [367, '', 55.711667, 15.986667, 'waypoint'], [368, '', 55.852804, 17.134264, 'waypoint'], [369, '', 55.91843, 17.68821, 'waypoint'], [370, '', 55.953855, 17.790394, 'waypoint'], [371, '', 56.260168, 18.668721, 'waypoint'], [372, '', 56.318174, 18.83707, 'waypoint'], [373, '', 56.387758, 18.914665, 'waypoint'], [374, '', 56.899017, 19.352017, 'waypoint'], [375, '', 57.325, 19.776667, 'waypoint'], [376, '', 58.043333, 20.351667, 'waypoint'], [377, '', 59.600466, 21.332732, 'waypoint'], [378, 'Pilots', 59.68705, 21.32565, 'pilot_station'], [379, '', 59.762667, 21.351217, 'waypoint'], [380, '', 59.8141, 21.336267, 'waypoint'], [381, '', 59.866667, 21.35295, 'waypoint'], [382, '', 59.99195, 21.116983, 'waypoint'], [383, '', 60.130067, 21.323917, 'waypoint'], [384, '', 60.177067, 21.44115, 'waypoint'], [385, '', 60.197583, 21.512017, 'waypoint'], [386, '', 60.212567, 21.600633, 'waypoint'], [387, '', 60.221183, 21.711567, 'waypoint'], [388, '', 60.249417, 21.8158, 'waypoint'], [389, '', 60.279567, 22.001917, 'waypoint'], [390, '', 60.377817, 22.104033, 'waypoint'], [391, '', 60.412733, 22.12865, 'waypoint'], [392, 'Turku', 60.42765, 22.19265, 'waypoint'], [393, '', 5.708333, 80.501667, 'waypoint'], [394, '', 5.708333, 80.545, 'waypoint'], [395, 'Dondra Head - E bound', 5.708333, 80.591667, 'named_waypoint'], [396, '', 5.708333, 80.691667, 'waypoint'], [397, '', 1.09214, 103.575613, 'waypoint'], [398, '', 1.052753, 103.633344, 'waypoint'], [399, '', 1.06148, 103.688424, 'waypoint'], [400, '', 1.083333, 103.72, 'waypoint'], [401, '', 1.23, 103.96, 'waypoint'], [402, '', 1.248333, 104.076667, 'waypoint'], [403, '', 1.26, 104.155, 'waypoint'], [404, '', 25.0, 122.29, 'waypoint'], [405, '', 25.15819, 122.113168, 'waypoint'], [406, '', 25.348333, 121.82, 'waypoint'], [407, '', 25.396667, 121.708333, 'waypoint'], [408, '', 25.471667, 121.531667, 'waypoint'], [409, '', 25.266667, 121.241667, 'waypoint'], [410, 'Pilots', 25.164492, 121.326391, 'waypoint'], [411, 'Taipei', 25.152255, 121.368042, 'waypoint'], [412, 'Freeport Brasos Terminal, Texas, U.S.A.', 28.938999, -95.339996, 'named_waypoint'], [413, '', 28.886117, -95.2441, 'waypoint'], [414, '', 28.356341, -94.714703, 'waypoint'], [415, '', 28.087417, -94.4165, 'waypoint'], [416, '', 27.718917, -94.414467, 'waypoint'], [417, '', 27.258926, -93.574924, 'waypoint'], [418, 'Exit North America - East Coast zone', 25.769876, -90.585914, 'zone_boundary'], [419, '', 24.108333, -87.295, 'waypoint'], [420, 'Yucatan Channel', 21.466667, -85.133333, 'strait'], [421, '', 16.773333, -80.151667, 'waypoint'], [422, '', 15.948333, -79.568333, 'waypoint'], [423, '', 9.564477, -79.873057, 'waypoint'], [424, 'Pilots', 9.438667, -79.919167, 'pilot_station'], [425, 'Colon (Caribbean Entrance To Panama Canal)', 9.388333, -79.919167, 'canal'], [426, '', 9.34405, -79.919383, 'waypoint'], [427, 'Gatun - Panama Canal Transit', 9.29905, -79.919583, 'waypoint'], [428, '', 9.211167, -79.924667, 'waypoint'], [429, '', 9.1792, -79.8682, 'waypoint'], [430, '', 9.159683, -79.814167, 'waypoint'], [431, '', 9.1204, -79.8054, 'waypoint'], [432, '', 9.11295, -79.769483, 'waypoint'], [433, 'Exit Special Areas - Oil zone', 9.119624, -79.732373, 'zone_boundary'], [434, '', 9.107467, -79.69085, 'waypoint'], [435, '', 9.068817, -79.672017, 'waypoint'], [436, '', 9.039383, -79.644717, 'waypoint'], [437, '', 9.017583, -79.613683, 'waypoint'], [438, 'Balboa (Pacific Entrance To Panama Canal)', 8.992333, -79.5878, 'waypoint'], [439, 'Balboa', 8.953333, -79.570833, 'named_waypoint'], [440, 'Pilots', 8.885, -79.518333, 'pilot_station'], [441, '', 8.832028, -79.473796, 'waypoint'], [442, '', 8.738335, -79.459743, 'waypoint'], [443, '', 8.583333, -79.45, 'waypoint'], [444, '', 7.75, -79.45, 'waypoint'], [445, '', 7.0, -79.4, 'waypoint'], [446, '', 3.935, -77.693333, 'waypoint'], [447, '', 3.798333, -77.383333, 'waypoint'], [448, '', 3.794183, -77.320833, 'waypoint'], [449, '', 3.794283, -77.239467, 'waypoint'], [450, '', 3.8048, -77.203333, 'waypoint'], [451, '', 3.822867, -77.172817, 'waypoint'], [452, '', 3.84305, -77.127817, 'waypoint'], [453, 'Buenaventura', 3.8673, -77.08925, 'waypoint'], [454, 'Fremantle', -32.046667, 115.745, 'named_waypoint'], [455, '', -32.045, 115.690633, 'waypoint'], [456, '', -32.005944, 115.693638, 'waypoint'], [457, '', -31.943167, 115.637817, 'waypoint'], [458, 'Outer Pilots', -31.923533, 115.601433, 'pilot_station'], [459, '', -31.868867, 115.5114, 'waypoint'], [460, '', -31.305, 114.935, 'waypoint'], [461, '', -28.79, 113.213333, 'waypoint'], [462, '', -25.523333, 112.403333, 'waypoint'], [463, 'Lombok Strait', -8.751667, 115.716667, 'strait'], [464, '', -8.306667, 115.885, 'waypoint'], [465, '', -7.175349, 114.972965, 'waypoint'], [466, '', -7.045, 114.868333, 'waypoint'], [467, '', -5.68, 112.895, 'waypoint'], [468, 'Java Sea', -4.291667, 110.025, 'named_waypoint'], [469, '', -3.776667, 109.61, 'waypoint'], [470, '', -2.756667, 109.595, 'waypoint'], [471, '', -2.433333, 109.0, 'waypoint'], [472, '', -2.363333, 108.846667, 'waypoint'], [473, '', -2.323333, 108.591667, 'waypoint'], [474, '', -2.238333, 108.46, 'waypoint'], [475, '', -1.826667, 108.271667, 'waypoint'], [476, '', -1.471667, 107.935, 'waypoint'], [477, '', -0.668736, 107.169983, 'waypoint'], [478, '', -0.206667, 106.73, 'waypoint'], [479, '', 0.831667, 106.271667, 'waypoint'], [480, '', 1.45, 105.305, 'waypoint'], [481, '', 1.553333, 104.65, 'waypoint'], [482, '', 1.205, 103.811667, 'waypoint'], [483, 'Klaipeda', 55.7025, 21.12, 'named_waypoint'], [484, '', 55.734517, 20.830017, 'waypoint'], [485, '', 55.726933, 20.678283, 'waypoint'], [486, '', 56.021895, 17.777389, 'waypoint'], [487, '', 55.984614, 17.671132, 'waypoint'], [488, '', 55.913155, 17.221661, 'waypoint'], [489, '', 55.538333, 14.878333, 'waypoint'], [490, '', 55.43, 14.585, 'waypoint'], [491, '', 55.218333, 14.281667, 'waypoint'], [492, '', 55.206667, 14.06, 'waypoint'], [493, 'Drogden Pilots', 55.516162, 12.711058, 'pilot_station'], [494, '', 56.628214, 5.516676, 'waypoint'], [495, '', 55.922367, 4.478217, 'waypoint'], [496, '', 55.588179, 4.305357, 'waypoint'], [497, '', 55.266083, 4.211167, 'waypoint'], [498, '', 54.076607, 3.474403, 'waypoint'], [499, '', 53.963333, 3.31, 'waypoint'], [500, '', 53.8769, 3.2099, 'waypoint'], [501, '', 53.75, 3.063333, 'waypoint'], [502, '', 53.543333, 2.921667, 'waypoint'], [503, '', 53.066667, 2.633333, 'waypoint'], [504, '', 52.926677, 2.637904, 'waypoint'], [505, '', 52.871853, 2.639193, 'waypoint'], [506, '', 52.696376, 2.645405, 'waypoint'], [507, '', 52.193333, 2.661667, 'waypoint'], [508, '', 51.926667, 2.633333, 'waypoint'], [509, '', 51.541952, 2.094744, 'waypoint'], [510, '', 51.376667, 1.865, 'waypoint'], [511, '', 51.225, 1.75, 'waypoint'], [512, 'Dover - SW bound', 51.033333, 1.38, 'headland'], [513, '', 50.6, 0.566667, 'waypoint'], [514, '', 50.068581, -2.446513, 'waypoint'], [515, '', 49.983333, -2.926667, 'waypoint'], [516, 'Exit North Sea zone, Exit Special Areas - Garbage zone, Enter Special Areas - Oil and Garbage zone', 49.201941, -5.0, 'zone_boundary'], [517, '', 48.99, -5.556667, 'waypoint'], [518, 'Ushant - SW bound', 48.9, -5.8, 'headland'], [519, '', 48.678333, -5.988333, 'waypoint'], [520, 'Exit Special Areas - Oil and Garbage zone', 48.45, -6.1771, 'zone_boundary'], [521, '', 43.65, -9.963333, 'waypoint'], [522, '', 43.5, -10.066667, 'waypoint'], [523, '', 43.308333, -10.2, 'waypoint'], [524, 'Finisterre - S bound', 42.883333, -10.2, 'headland'], [525, '', 42.716667, -10.2, 'waypoint'], [526, '', 39.0, -10.2, 'waypoint'], [527, '', 38.866667, -10.2, 'waypoint'], [528, '', 38.683333, -10.2, 'waypoint'], [529, '', 38.575, -10.166667, 'waypoint'], [530, '', 38.506667, -10.146667, 'waypoint'], [531, '', 37.025, -9.71, 'waypoint'], [532, '', 36.95, -9.686667, 'waypoint'], [533, '', 36.76, -9.631667, 'waypoint'], [534, '', 36.503333, -9.336667, 'waypoint'], [535, '', 36.448333, -9.095, 'waypoint'], [536, '', 36.391667, -8.863333, 'waypoint'], [537, '', 35.9, -6.2, 'waypoint'], [538, 'Enter Special Areas - Garbage zone', 35.916667, -5.6, 'zone_boundary'], [539, '', 35.937117, -5.529083, 'waypoint'], [540, '', 35.95, -5.481667, 'waypoint'], [541, '', 35.966667, -5.426667, 'waypoint'], [542, '', 36.373333, -2.186667, 'waypoint'], [543, '', 37.55, -0.518333, 'waypoint'], [544, '', 37.583333, -0.49, 'waypoint'], [545, '', 38.615, 0.4, 'waypoint'], [546, '', 38.686667, 0.458333, 'waypoint'], [547, '', 42.861667, 6.551667, 'waypoint'], [548, '', 43.811667, 8.281667, 'waypoint'], [549, '', 44.318997, 8.975197, 'waypoint'], [550, 'Pilots', 44.378217, 8.956067, 'pilot_station'], [551, 'Houston', 29.75, -95.289167, 'named_waypoint'], [552, '', 29.726367, -95.261233, 'waypoint'], [553, 'Pasadena', 29.724583, -95.220667, 'waypoint'], [554, '', 29.7453, -95.18725, 'waypoint'], [555, '', 29.735933, -95.1475, 'waypoint'], [556, 'Intercontinental Terminals (Houston Ship Canal)', 29.742067, -95.1074, 'waypoint'], [557, '', 29.757213, -95.068341, 'waypoint'], [558, '', 29.731283, -95.043567, 'waypoint'], [559, '', 29.705817, -95.018467, 'waypoint'], [560, '', 29.685033, -94.98285, 'waypoint'], [561, '', 29.61435, -94.95535, 'waypoint'], [562, '', 29.49435, -94.865917, 'waypoint'], [563, '', 29.367467, -94.802233, 'waypoint'], [564, '', 29.342417, -94.769283, 'waypoint'], [565, '', 29.34565, -94.71555, 'waypoint'], [566, 'Pilots', 29.304983, -94.62125, 'pilot_station'], [567, '', 29.265, -94.591667, 'waypoint'], [568, '', 29.141667, -94.428333, 'waypoint'], [569, '', 29.138333, -94.358333, 'waypoint'], [570, '', 28.943333, -94.046667, 'waypoint'], [571, '', 28.722432, -93.692574, 'waypoint'], [572, '', 28.223333, -92.895, 'waypoint'], [573, '', 27.855, -92.575, 'waypoint'], [574, '', 27.216667, -91.025, 'waypoint'], [575, '', 27.061667, -90.793333, 'waypoint'], [576, 'Exit North America - East Coast zone', 25.87799, -87.978952, 'zone_boundary'], [577, 'Enter North America - East Coast zone', 25.244332, -86.484101, 'zone_boundary'], [578, '', 24.613333, -85.003333, 'waypoint'], [579, '', 23.888333, -81.666667, 'waypoint'], [580, 'Exit North America - East Coast zone', 24.124109, -81.052058, 'zone_boundary'], [581, '', 24.383333, -80.375, 'waypoint'], [582, 'Enter North America - East Coast zone', 24.561154, -80.194626, 'zone_boundary'], [583, '', 25.001667, -79.746667, 'waypoint'], [584, 'Exit North America - East Coast zone', 25.446435, -79.70314, 'zone_boundary'], [585, 'Enter North America - East Coast zone', 26.036354, -79.645158, 'zone_boundary'], [586, 'Exit North America - East Coast zone', 26.853774, -79.564323, 'zone_boundary'], [587, 'Florida Strait', 27.5, -79.5, 'strait'], [588, 'Enter North America - East Coast zone', 28.286751, -78.42504, 'zone_boundary'], [589, 'Exit North America - East Coast zone', 29.346941, -76.931542, 'zone_boundary'], [590, 'Exit Special Areas - Oil zone', 29.552156, -76.636092, 'zone_boundary'], [591, '', 42.500017, -50.0, 'waypoint'], [592, 'Enter Special Areas - Oil and Garbage zone', 49.667514, -7.545929, 'zone_boundary'], [593, '', 49.633333, -6.548333, 'waypoint'], [594, 'Bishop Rock - South - E bound', 49.633333, -6.333333, 'named_waypoint'], [595, 'Exit Special Areas - Oil and Garbage zone, Enter North Sea zone, Enter Special Areas - Garbage zone', 49.707499, -5.0, 'zone_boundary'], [596, 'Jebel Ali', 24.991667, 55.055, 'named_waypoint'], [597, '', 25.024693, 55.039923, 'waypoint'], [598, '', 25.12, 54.936667, 'waypoint'], [599, 'Pilots', 25.153223, 54.901302, 'pilot_station'], [600, '', 25.256667, 54.823333, 'waypoint'], [601, '', 25.825, 55.293333, 'waypoint'], [602, 'Mina Saqr Offshore RV', 26.176667, 55.87, 'named_waypoint'], [603, '', 26.273333, 56.015, 'waypoint'], [604, '', 26.518333, 56.376667, 'waypoint'], [605, '', 26.561667, 56.48, 'waypoint'], [606, 'Quoins - E bound', 26.56, 56.518333, 'named_waypoint'], [607, '', 26.461667, 56.615, 'waypoint'], [608, '', 25.81, 57.046667, 'waypoint'], [609, '', 25.766667, 57.073333, 'waypoint'], [610, '', 25.668333, 57.133333, 'waypoint'], [611, '', 25.576667, 57.216667, 'waypoint'], [612, '', 25.538333, 57.255, 'waypoint'], [613, 'Exit Special Areas - Garbage zone', 22.665336, 59.873896, 'zone_boundary'], [614, '', 22.538333, 59.988333, 'waypoint'], [615, '', 22.425, 59.988333, 'waypoint'], [616, '', 20.42, 59.131667, 'waypoint'], [617, '', 18.883333, 57.985, 'waypoint'], [618, '', 17.338333, 56.515, 'waypoint'], [619, 'Enter Piracy zone', 17.086367, 56.205387, 'zone_boundary'], [620, 'Exit Special Areas - Oil - Oman area of the Arabian Sea zone', 15.135985, 53.822563, 'zone_boundary'], [621, '', 54.003333, 4.728333, 'waypoint'], [622, '', 54.141667, 6.353333, 'waypoint'], [623, '', 54.155, 7.453333, 'waypoint'], [624, '', 54.15565, 7.550117, 'waypoint'], [625, '', 53.993333, 8.058333, 'waypoint'], [626, 'Elbe Inward Pilots', 53.993333, 8.115, 'waypoint'], [627, '', 53.995, 8.303333, 'waypoint'], [628, '', 53.978333, 8.453333, 'waypoint'], [629, '', 53.965, 8.586667, 'waypoint'], [630, '', 53.935, 8.66, 'waypoint'], [631, '', 53.875, 8.715, 'waypoint'], [632, '', 53.843333, 8.775, 'waypoint'], [633, '', 53.838333, 8.836667, 'waypoint'], [634, '', 53.85, 8.98, 'waypoint'], [635, 'Brunsbuttel', 53.878333, 9.098333, 'waypoint'], [636, '', 53.880433, 9.21675, 'waypoint'], [637, '', 53.863183, 9.29425, 'waypoint'], [638, '', 53.833217, 9.3507, 'waypoint'], [639, '', 53.752767, 9.40555, 'waypoint'], [640, '', 53.72945, 9.452217, 'waypoint'], [641, '', 53.696817, 9.497317, 'waypoint'], [642, '', 53.648583, 9.51855, 'waypoint'], [643, '', 53.603433, 9.585533, 'waypoint'], [644, '', 53.57005, 9.652783, 'waypoint'], [645, '', 53.559367, 9.7767, 'waypoint'], [646, '', 53.542267, 9.872317, 'waypoint'], [647, 'Hamburg', 53.541667, 9.931667, 'named_waypoint'], [648, '', 37.566667, 10.041667, 'waypoint'], [649, '', 37.566667, 10.221667, 'waypoint'], [650, '', 37.385, 11.133333, 'waypoint'], [651, '', 37.313333, 11.286667, 'waypoint'], [652, 'Cape Matapan', 36.303333, 22.488333, 'headland'], [653, '', 36.406539, 22.948937, 'waypoint'], [654, '', 36.363937, 23.108279, 'waypoint'], [655, '', 36.393333, 23.241667, 'waypoint'], [656, '', 36.821667, 23.525, 'waypoint'], [657, '', 37.435003, 24.019997, 'waypoint'], [658, '', 37.575, 24.101667, 'waypoint'], [659, '', 37.715, 24.225, 'waypoint'], [660, '', 37.87, 24.561667, 'waypoint'], [661, '', 37.958333, 24.615, 'waypoint'], [662, '', 39.876667, 25.825, 'waypoint'], [663, '', 39.98, 26.013333, 'waypoint'], [664, 'Dardanelles - N bound', 40.008333, 26.133333, 'named_waypoint'], [665, '', 40.018333, 26.193333, 'waypoint'], [666, '', 40.025, 26.245, 'waypoint'], [667, '', 40.065, 26.315, 'waypoint'], [668, '', 40.135, 26.388333, 'waypoint'], [669, '', 40.193333, 26.386667, 'waypoint'], [670, '', 40.218333, 26.465, 'waypoint'], [671, '', 40.305, 26.601667, 'waypoint'], [672, '', 40.345, 26.648333, 'waypoint'], [673, '', 40.376667, 26.676667, 'waypoint'], [674, '', 40.43, 26.756667, 'waypoint'], [675, '', 40.509803, 26.999984, 'waypoint'], [676, '', 40.564426, 27.166667, 'waypoint'], [677, '', 40.648146, 27.422102, 'waypoint'], [678, '', 40.72, 27.641667, 'waypoint'], [679, '', 40.736589, 27.790927, 'waypoint'], [680, '', 40.763617, 28.032732, 'waypoint'], [681, '', 40.84, 28.718333, 'waypoint'], [682, '', 40.858333, 28.88, 'waypoint'], [683, '', 40.89, 28.926667, 'waypoint'], [684, '', 40.953333, 28.985, 'waypoint'], [685, 'Exit Special Areas - Garbage zone, Enter Black Sea - Special Areas - Garbage and Chemicals zone', 40.991667, 28.998333, 'waypoint'], [686, 'Lagos Container Terminal, Nigeria', 6.435, 3.388333, 'named_waypoint'], [687, '', 6.402917, 3.399183, 'waypoint'], [688, 'Pilots', 6.365194, 3.413151, 'pilot_station'], [689, 'Pilots', 6.308333, 3.423333, 'pilot_station'], [690, '', 6.217833, 3.3999, 'waypoint'], [691, 'Offshore Lagos No.11 (TA)', 6.19, 3.375, 'named_waypoint'], [692, 'Enter Special Areas - Oil - South Africa zone', -32.275634, 16.979583, 'zone_boundary'], [693, 'Miami', 25.766667, -80.141667, 'named_waypoint'], [694, 'Pilots', 25.766433, -80.0829, 'waypoint'], [695, 'Exit North America - East Coast zone', 25.860913, -79.700215, 'zone_boundary'], [696, '', 25.871667, -79.66, 'waypoint'], [697, 'Enter North America - East Coast zone', 28.286719, -78.718971, 'zone_boundary'], [698, 'Exit Special Areas - Oil zone', 29.818924, -77.150227, 'zone_boundary'], [699, 'Enter North America - East Coast zone', 31.103063, -75.782175, 'zone_boundary'], [700, 'Exit North America - East Coast zone', 34.747547, -71.583184, 'zone_boundary'], [701, 'Enter North America - East Coast zone', 40.424197, -63.750634, 'zone_boundary'], [702, 'Cape Race - Seasonal', 46.266667, -52.815, 'headland'], [703, 'Exit North America - East Coast zone', 49.065436, -48.051941, 'zone_boundary'], [704, 'Enter Special Areas - Oil and Garbage zone', 59.352957, -7.514161, 'zone_boundary'], [705, 'Exit Special Areas - Oil and Garbage zone, Enter North Sea zone, Enter Special Areas - Garbage zone', 59.485933, -4.0, 'zone_boundary'], [706, '', 59.516667, -2.25, 'waypoint'], [707, 'Fair Isle - South Passage', 59.45, -2.0, 'strait'], [708, '', 58.605817, 1.273917, 'waypoint'], [709, '', 58.530133, 1.64375, 'waypoint'], [710, '', 58.5524, 1.842433, 'waypoint'], [711, '', 57.756444, 6.482834, 'waypoint'], [712, '', 57.719326, 6.575371, 'waypoint'], [713, '', 57.718674, 6.689825, 'waypoint'], [714, '', 57.688039, 7.695557, 'waypoint'], [715, '', 57.684779, 7.813664, 'waypoint'], [716, '', 57.683474, 7.984127, 'waypoint'], [717, '', 59.08, 21.785, 'waypoint'], [718, '', 59.413333, 22.618333, 'waypoint'], [719, '', 59.731667, 24.373333, 'waypoint'], [720, '', 59.795, 25.0, 'waypoint'], [721, '', 59.812333, 25.185167, 'waypoint'], [722, '', 59.853436, 25.630255, 'waypoint'], [723, '', 59.865, 25.776667, 'waypoint'], [724, '', 59.877926, 25.870609, 'waypoint'], [725, '', 59.966455, 26.492115, 'waypoint'], [726, '', 59.991667, 26.673333, 'waypoint'], [727, '', 59.963333, 27.053333, 'waypoint'], [728, '', 60.181667, 27.781667, 'waypoint'], [729, '', 60.12, 28.26, 'waypoint'], [730, '', 60.08458, 28.335297, 'waypoint'], [731, '', 60.05185, 28.41765, 'waypoint'], [732, '', 60.0393, 28.531617, 'waypoint'], [733, '', 60.044545, 28.610208, 'waypoint'], [734, 'Pilots', 60.028496, 29.351532, 'waypoint'], [735, '', 60.025151, 29.494809, 'waypoint'], [736, '', 59.990924, 29.696931, 'waypoint'], [737, 'Kronshtadt', 59.979983, 29.76055, 'named_waypoint'], [738, 'St Petersburg, Russia', 59.886517, 30.174483, 'waypoint'], [739, 'Bombay', 18.916667, 72.868333, 'named_waypoint'], [740, 'Pilots', 18.871483, 72.841533, 'waypoint'], [741, '', 18.84295, 72.7858, 'waypoint'], [742, '', 18.845653, 72.73896, 'waypoint'], [743, '', 18.837405, 72.693366, 'waypoint'], [744, '', 18.853367, 72.5732, 'waypoint'], [745, '', 18.832983, 72.54445, 'waypoint'], [746, '', 18.493317, 72.490117, 'waypoint'], [747, '', 18.234133, 72.5322, 'waypoint'], [748, '', 18.141617, 72.569367, 'waypoint'], [749, '', 17.967317, 72.598983, 'waypoint'], [750, '', 17.502004, 72.677777, 'waypoint'], [751, '', 15.671667, 73.018333, 'waypoint'], [752, 'SW Australia Outer', -34.63, 114.593333, 'named_waypoint'], [753, '', -35.466667, 116.416667, 'waypoint'], [754, '', -38.53, 138.845, 'waypoint'], [755, '', -39.056667, 142.960033, 'waypoint'], [756, '', -39.181667, 143.511667, 'waypoint'], [757, '', -39.237368, 145.151583, 'waypoint'], [758, '', -39.261113, 145.84974, 'waypoint'], [759, '', -39.285, 146.553333, 'waypoint'], [760, '', -39.145167, 146.950355, 'waypoint'], [761, '', -38.944273, 147.707971, 'waypoint'], [762, '', -38.778333, 148.268333, 'waypoint'], [763, '', -38.720302, 148.368062, 'waypoint'], [764, '', -37.835, 150.393333, 'waypoint'], [765, '', -35.166667, 151.361667, 'waypoint'], [766, '', -33.923333, 151.648333, 'waypoint'], [767, 'Pilots', -33.848267, 151.359067, 'pilot_station'], [768, '', -33.823767, 151.2818, 'waypoint'], [769, 'Sydney, N.S.W., Australia', -33.855301, 151.250007, 'waypoint'], [770, 'Enter Special Areas - Oil - Oman area of the Arabian Sea zone', 19.054741, 62.140435, 'zone_boundary'], [771, 'Enter Piracy zone', 16.468393, 56.969884, 'zone_boundary'], [772, 'Exit Special Areas - Oil - Oman area of the Arabian Sea zone', 14.956288, 53.979874, 'zone_boundary'], [773, '', 20.246541, 120.666556, 'waypoint'], [774, '', 21.366667, 121.766667, 'waypoint'], [775, '', 26.068847, 128.084741, 'waypoint'], [776, '', 34.163333, 139.36, 'waypoint'], [777, '', 35.043333, 140.503333, 'waypoint'], [778, '', 35.658333, 141.08, 'waypoint'], [779, '', 35.756667, 141.08, 'waypoint'], [780, '', 36.874167, 140.8984, 'waypoint'], [781, 'Onahama', 36.92085, 140.887117, 'waypoint'], [782, 'Punta Arenas', -53.175, -70.903333, 'named_waypoint'], [783, '', -53.188333, -70.85, 'waypoint'], [784, '', -53.21, -70.806667, 'waypoint'], [785, '', -53.218333, -70.715, 'waypoint'], [786, '', -53.135233, -70.657367, 'waypoint'], [787, '', -52.960383, -70.489067, 'waypoint'], [788, '', -52.775117, -70.4782, 'waypoint'], [789, '', -52.737167, -70.432633, 'waypoint'], [790, '', -52.718717, -70.300667, 'waypoint'], [791, '', -52.68265, -70.04165, 'waypoint'], [792, '', -52.566867, -69.664383, 'waypoint'], [793, '', -52.488333, -69.571667, 'waypoint'], [794, 'Punta Delgada', -52.461667, -69.51, 'named_waypoint'], [795, '', -52.4155, -69.42695, 'waypoint'], [796, '', -52.353333, -69.313333, 'waypoint'], [797, '', -52.353333, -69.135, 'waypoint'], [798, 'Dungeness - Atlantic Exit Of Magellan Strait', -52.37, -69.033333, 'strait'], [799, '', -52.511667, -68.5, 'waypoint'], [800, '', -52.785, -68.075, 'waypoint'], [801, '', -54.528333, -64.928333, 'waypoint'], [802, '', -54.733333, -64.86, 'waypoint'], [803, '', -56.015783, -66.200633, 'waypoint'], [804, 'Cape Horn', -56.15, -67.221667, 'headland'], [805, '', -56.15, -120.701667, 'waypoint'], [806, '', -21.095, 164.288333, 'waypoint'], [807, '', -19.605, 163.065, 'waypoint'], [808, '', -6.646667, 154.628333, 'waypoint'], [809, '', -4.278333, 153.435, 'waypoint'], [810, '', -3.725, 152.905, 'waypoint'], [811, '', -3.095, 151.978333, 'waypoint'], [812, '', -1.53, 150.803333, 'waypoint'], [813, '', 7.35, 143.656667, 'waypoint'], [814, '', 26.863333, 128.441667, 'waypoint'], [815, '', 27.013333, 128.268333, 'waypoint'], [816, '', 29.28, 125.58, 'waypoint'], [817, '', 29.565317, 125.10415, 'waypoint'], [818, '', 31.110033, 123.025717, 'waypoint'], [819, '', 31.112017, 122.645477, 'waypoint'], [820, '', 31.113132, 122.559474, 'waypoint'], [821, '', 31.104332, 122.493784, 'waypoint'], [822, 'Changjiangkou Inbound Pilots', 31.104333, 122.4, 'pilot_station'], [823, '', 31.104332, 122.357505, 'waypoint'], [824, '', 31.108123, 122.296843, 'waypoint'], [825, '', 31.165256, 122.20014, 'waypoint'], [826, '', 31.224099, 122.104962, 'waypoint'], [827, '', 31.239419, 122.046415, 'waypoint'], [828, '', 31.269817, 121.862805, 'waypoint'], [829, '', 31.285168, 121.82089, 'waypoint'], [830, '', 31.311215, 121.749271, 'waypoint'], [831, '', 31.325025, 121.712791, 'waypoint'], [832, '', 31.37452, 121.610439, 'waypoint'], [833, '', 31.404753, 121.547127, 'waypoint'], [834, 'Baoshan', 31.391944, 121.510222, 'waypoint'], [835, '', 31.358133, 121.502651, 'waypoint'], [836, '', 31.341673, 121.541262, 'waypoint'], [837, '', 31.31033, 121.556595, 'waypoint'], [838, 'Shanghai', 31.276893, 121.563988, 'waypoint'], [839, '', -40.0, 45.0, 'waypoint'], [840, '', -49.844825, 18.131409, 'waypoint'], [841, '', -53.716667, -14.0, 'waypoint'], [842, '', -53.716667, -24.0, 'waypoint'], [843, '', -53.716667, -38.233333, 'waypoint'], [844, '', -52.785, -67.803333, 'waypoint'], [845, '', -53.185, -70.69, 'waypoint'], [846, 'Santos', -23.965, -46.298333, 'named_waypoint'], [847, 'Pilots', -23.993767, -46.32605, 'waypoint'], [848, '', -24.05335, -46.3571, 'waypoint'], [849, '', -24.131683, -46.16615, 'waypoint'], [850, '', -24.240459, -45.848904, 'waypoint'], [851, '', -24.25, -45.598333, 'waypoint'], [852, '', -23.1875, -41.976467, 'waypoint'], [853, '', -22.838333, -41.303333, 'waypoint'], [854, '', -21.753333, -40.273333, 'waypoint'], [855, '', -21.341667, -39.9, 'waypoint'], [856, '', -18.645, -38.163333, 'waypoint'], [857, '', -17.87, -38.0, 'waypoint'], [858, '', -8.805, -34.67, 'waypoint'], [859, '', -8.263333, -34.51, 'waypoint'], [860, '', 17.225, -25.85, 'waypoint'], [861, 'Enter Special Areas - Oil and Garbage zone', 48.45, -5.959617, 'zone_boundary'], [862, '', 31.095, 122.686667, 'waypoint'], [863, '', 31.090659, 122.73716, 'waypoint'], [864, '', 31.47645, 123.65575, 'waypoint'], [865, '', 32.3, 125.183333, 'waypoint'], [866, '', 33.24, 127.113333, 'waypoint'], [867, '', 34.473333, 128.785, 'waypoint'], [868, '', 41.331667, 140.268333, 'waypoint'], [869, 'Tugaru - North And South Japan', 41.638333, 140.948333, 'named_waypoint'], [870, '', 41.735, 143.251667, 'waypoint'], [871, 'Enter North America - West Coast zone', 37.523149, -127.467566, 'zone_boundary'], [872, '', 33.63035, -121.115033, 'waypoint'], [873, 'Exit North America - West Coast zone, Enter US California zone', 33.634641, -120.681168, 'zone_boundary'], [874, '', 33.6507, -119.057067, 'waypoint'], [875, '', 33.603505, -118.346026, 'waypoint'], [876, '', 33.598333, -118.27, 'waypoint'], [877, '', 33.638333, -118.231667, 'waypoint'], [878, 'Pilots', 33.690017, -118.1806, 'pilot_station'], [879, '', 33.723233, -118.18375, 'waypoint'], [880, 'Los Angeles', 33.746267, -118.217367, 'waypoint'], [881, '', 51.415, 2.013333, 'waypoint'], [882, '', 51.451667, 1.96825, 'waypoint'], [883, '', 51.531667, 1.865, 'waypoint'], [884, '', 51.645, 1.821667, 'waypoint'], [885, '', 51.708333, 1.81, 'waypoint'], [886, '', 51.833333, 1.788333, 'waypoint'], [887, '', 51.861667, 1.701667, 'waypoint'], [888, '', 51.858992, 1.646735, 'waypoint'], [889, '', 51.858721, 1.583531, 'waypoint'], [890, '', 51.896817, 1.56085, 'waypoint'], [891, '', 51.932833, 1.5471, 'waypoint'], [892, '', 51.934636, 1.452013, 'waypoint'], [893, '', 51.92971, 1.380393, 'waypoint'], [894, '', 51.925164, 1.31774, 'waypoint'], [895, 'Felixstowe', 51.956667, 1.3, 'named_waypoint'], [896, 'Trieste', 45.631667, 13.745, 'named_waypoint'], [897, '', 45.615, 13.686667, 'waypoint'], [898, '', 45.63, 13.546667, 'waypoint'], [899, '', 45.561667, 13.315, 'waypoint'], [900, '', 45.368333, 12.963333, 'waypoint'], [901, '', 45.325, 12.976667, 'waypoint'], [902, '', 45.13, 13.043333, 'waypoint'], [903, '', 44.896667, 13.291667, 'waypoint'], [904, '', 44.085, 14.04, 'waypoint'], [905, '', 43.945, 14.2, 'waypoint'], [906, '', 42.32, 16.0, 'waypoint'], [907, '', 42.094, 16.3208, 'waypoint'], [908, '', 40.383333, 18.703333, 'waypoint'], [909, '', 39.755, 18.76, 'waypoint'], [910, '', 36.6, 15.341667, 'waypoint'], [911, '', 36.475, 15.071667, 'waypoint'], [912, '', 36.437453, 14.324879, 'waypoint'], [913, 'Enter North America - East Coast zone', 46.163958, -48.255294, 'zone_boundary'], [914, '', 46.276667, -54.088333, 'waypoint'], [915, '', 46.541667, -56.303333, 'waypoint'], [916, '', 47.536667, -59.473333, 'waypoint'], [917, '', 47.713333, -59.926667, 'waypoint'], [918, '', 48.015, -60.668333, 'waypoint'], [919, '', 48.493333, -61.85, 'waypoint'], [920, '', 49.218333, -63.686667, 'waypoint'], [921, '', 49.368333, -64.141667, 'waypoint'], [922, '', 49.461667, -65.841667, 'waypoint'], [923, '', 49.221617, -67.36935, 'waypoint'], [924, '', 48.61745, -68.77775, 'waypoint'], [925, '', 48.499933, -69.04915, 'waypoint'], [926, 'Pilots', 48.34055, -69.316467, 'pilot_station'], [927, '', 48.098017, -69.580533, 'waypoint'], [928, '', 48.061789, -69.612787, 'waypoint'], [929, '', 48.0, -69.666667, 'waypoint'], [930, '', 47.96325, -69.698917, 'waypoint'], [931, '', 47.807283, -69.819733, 'waypoint'], [932, '', 47.677333, -69.943767, 'waypoint'], [933, '', 47.61155, -70.062767, 'waypoint'], [934, '', 47.500083, -70.1661, 'waypoint'], [935, '', 47.455617, -70.251433, 'waypoint'], [936, '', 47.42025, -70.437733, 'waypoint'], [937, '', 47.266783, -70.539033, 'waypoint'], [938, '', 47.199233, -70.60595, 'waypoint'], [939, '', 47.158133, -70.659367, 'waypoint'], [940, '', 47.109717, -70.705933, 'waypoint'], [941, '', 47.0644, -70.7352, 'waypoint'], [942, '', 46.931083, -70.862867, 'waypoint'], [943, '', 46.859217, -70.978933, 'waypoint'], [944, '', 46.84265, -71.05425, 'waypoint'], [945, '', 46.8413, -71.147617, 'waypoint'], [946, '', 46.82245, -71.188917, 'waypoint'], [947, '', 46.78235, -71.2176, 'waypoint'], [948, '', 46.755167, -71.25915, 'waypoint'], [949, '', 46.735517, -71.3321, 'waypoint'], [950, '', 46.702833, -71.50815, 'waypoint'], [951, '', 46.681367, -71.557767, 'waypoint'], [952, '', 46.66625, -71.6101, 'waypoint'], [953, '', 46.63975, -71.7011, 'waypoint'], [954, '', 46.6794, -71.846867, 'waypoint'], [955, '', 46.658683, -71.894067, 'waypoint'], [956, '', 46.607383, -71.980283, 'waypoint'], [957, '', 46.566467, -72.061717, 'waypoint'], [958, '', 46.564467, -72.113483, 'waypoint'], [959, '', 46.53325, -72.17895, 'waypoint'], [960, '', 46.509367, -72.224667, 'waypoint'], [961, '', 46.469733, -72.244683, 'waypoint'], [962, '', 46.440983, -72.275917, 'waypoint'], [963, '', 46.4364, -72.338883, 'waypoint'], [964, '', 46.413841, -72.379108, 'waypoint'], [965, '', 46.382433, -72.4337, 'waypoint'], [966, '', 46.368283, -72.489833, 'waypoint'], [967, '', 46.32985, -72.539417, 'waypoint'], [968, '', 46.292683, -72.585067, 'waypoint'], [969, '', 46.26775, -72.631833, 'waypoint'], [970, '', 46.264083, -72.6834, 'waypoint'], [971, '', 46.21125, -72.817117, 'waypoint'], [972, '', 46.192233, -72.892233, 'waypoint'], [973, '', 46.165567, -72.936117, 'waypoint'], [974, '', 46.1187, -72.95925, 'waypoint'], [975, '', 46.067517, -73.040167, 'waypoint'], [976, '', 46.059983, -73.092467, 'waypoint'], [977, '', 46.048417, -73.14745, 'waypoint'], [978, '', 45.984317, -73.1849, 'waypoint'], [979, '', 45.95155, -73.210317, 'waypoint'], [980, '', 45.9081, -73.214583, 'waypoint'], [981, '', 45.860217, -73.266767, 'waypoint'], [982, '', 45.786817, -73.34705, 'waypoint'], [983, '', 45.72405, -73.427067, 'waypoint'], [984, '', 45.68765, -73.453217, 'waypoint'], [985, '', 45.651167, -73.474833, 'waypoint'], [986, '', 45.60995, -73.502167, 'waypoint'], [987, '', 45.5661, -73.509983, 'waypoint'], [988, 'Montreal', 45.536667, -73.535, 'named_waypoint'], [989, 'Odessa', 46.493333, 30.751667, 'named_waypoint'], [990, 'Pilots', 46.496667, 30.815, 'pilot_station'], [991, '', 46.254883, 30.893967, 'waypoint'], [992, '', 46.11, 31.091667, 'waypoint'], [993, '', 41.351667, 29.138333, 'waypoint'], [994, '', 41.251667, 29.131667, 'waypoint'], [995, 'Bosporus - S bound', 41.203333, 29.11, 'named_waypoint'], [996, '', 41.156667, 29.056667, 'waypoint'], [997, '', 41.123333, 29.08, 'waypoint'], [998, '', 41.083333, 29.059167, 'waypoint'], [999, '', 41.051667, 29.040833, 'waypoint'], [1000, '', 41.026667, 28.996667, 'waypoint'], [1001, '', 40.938852, 28.913543, 'waypoint'], [1002, '', 40.905, 28.861667, 'waypoint'], [1003, '', 40.888333, 28.71, 'waypoint'], [1004, '', 40.83885, 28.27301, 'waypoint'], [1005, '', 40.812899, 28.041695, 'waypoint'], [1006, '', 40.800126, 27.927715, 'waypoint'], [1007, '', 40.784881, 27.792534, 'waypoint'], [1008, '', 40.766667, 27.631667, 'waypoint'], [1009, '', 40.681434, 27.404774, 'waypoint'], [1010, '', 40.016667, 25.99, 'waypoint'], [1011, '', 36.441667, 22.933333, 'waypoint'], [1012, '', 36.676667, 21.54, 'waypoint'], [1013, '', 37.178333, 20.905, 'waypoint'], [1014, '', 38.113333, 20.193333, 'waypoint'], [1015, '', 39.84675, 19.103517, 'waypoint'], [1016, '', 42.2, 16.323333, 'waypoint'], [1017, '', 42.458333, 16.0, 'waypoint'], [1018, '', 43.655, 14.448333, 'waypoint'], [1019, '', 43.798055, 14.23835, 'waypoint'], [1020, '', 43.853333, 14.068333, 'waypoint'], [1021, '', 43.951667, 13.855, 'waypoint'], [1022, '', 44.301667, 13.238333, 'waypoint'], [1023, '', 44.61, 13.096667, 'waypoint'], [1024, '', 44.758333, 13.026667, 'waypoint'], [1025, '', 44.856667, 12.978333, 'waypoint'], [1026, '', 44.971667, 12.903333, 'waypoint'], [1027, '', 45.135, 12.803333, 'waypoint'], [1028, '', 45.286667, 12.533333, 'waypoint'], [1029, '', 45.38, 12.526667, 'waypoint'], [1030, '', 45.4, 12.480983, 'waypoint'], [1031, '', 45.423813, 12.423406, 'waypoint'], [1032, '', 45.422817, 12.371783, 'waypoint'], [1033, 'Venice, Italy', 45.43005, 12.3184, 'waypoint']]

_GRAPH_EDGES = [[0, 2, 1.78], [2, 3, 2.17], [3, 4, 2.71], [4, 5, 2.29], [5, 6, 2.02], [6, 7, 2.08], [7, 8, 2.03], [8, 9, 3.08], [9, 10, 3.01], [10, 11, 2.8], [11, 12, 3.33], [12, 13, 2.37], [13, 14, 2.29], [14, 15, 2.49], [15, 16, 3.85], [16, 17, 5.6], [17, 18, 4.09], [18, 19, 2.86], [19, 20, 2.84], [20, 21, 5.06], [21, 22, 3.43], [22, 23, 2.38], [23, 24, 4.5], [24, 25, 8.24], [25, 26, 7.94], [26, 27, 4.04], [27, 28, 3.39], [28, 29, 31.65], [29, 30, 24.64], [30, 31, 19.44], [31, 32, 21.02], [32, 33, 7.48], [33, 34, 15.42], [34, 35, 23.25], [35, 36, 27.48], [36, 37, 11.3], [37, 38, 9.11], [38, 39, 10.58], [39, 40, 77.34], [40, 41, 84.83], [41, 42, 149.07], [42, 43, 21.59], [43, 44, 4.91], [44, 45, 2.39], [45, 46, 4.35], [46, 47, 25.14], [47, 48, 23.76], [48, 49, 10.61], [49, 50, 4.12], [50, 51, 6.68], [51, 52, 28.38], [52, 53, 6.4], [53, 54, 11.76], [54, 55, 5.87], [55, 56, 4.48], [56, 57, 4.8], [57, 58, 3.41], [58, 59, 2.44], [59, 60, 4.75], [60, 61, 2.81], [61, 62, 8.54], [62, 63, 8.1], [63, 64, 5.99], [64, 65, 3.28], [65, 66, 5.99], [66, 67, 49.79], [67, 68, 20.2], [68, 69, 18.0], [69, 70, 104.93], [70, 71, 14.03], [71, 72, 20.02], [72, 73, 4.76], [73, 74, 5.4], [74, 75, 4.13], [75, 76, 4.78], [76, 77, 2.06], [77, 78, 2.02], [78, 79, 2.05], [80, 81, 3.18], [81, 82, 4.23], [82, 83, 3.75], [83, 84, 22.63], [84, 85, 589.73], [85, 86, 97.29], [86, 87, 131.03], [87, 88, 30.64], [88, 89, 37.02], [89, 90, 1102.04], [90, 91, 34.93], [91, 92, 226.18], [92, 93, 109.88], [93, 94, 76.43], [94, 95, 7.81], [95, 96, 9.22], [96, 97, 7.53], [97, 98, 5.72], [98, 99, 6.63], [99, 100, 5.22], [100, 101, 2.15], [101, 102, 2.15], [102, 103, 4.13], [103, 104, 3.91], [104, 105, 5.08], [105, 106, 3.4], [106, 107, 5.38], [107, 108, 6.86], [108, 109, 17.25], [109, 110, 4.81], [110, 111, 21.87], [111, 112, 36.73], [112, 113, 14.72], [113, 114, 5.58], [114, 115, 24.06], [115, 116, 19.58], [116, 117, 29.78], [117, 118, 5.94], [118, 119, 2.82], [119, 120, 8.32], [120, 121, 57.7], [121, 122, 32.44], [122, 123, 147.2], [123, 124, 155.62], [124, 125, 4.72], [125, 126, 861.13], [126, 127, 5.57], [127, 128, 5.48], [128, 129, 23.88], [129, 130, 214.77], [130, 131, 59.1], [131, 132, 543.76], [132, 133, 115.04], [133, 134, 235.75], [134, 135, 43.81], [135, 136, 3.9], [136, 137, 9.12], [137, 138, 6.09], [138, 139, 2.79], [139, 140, 3.61], [140, 141, 7.85], [141, 142, 2.52], [142, 143, 4.59], [143, 144, 2.49], [144, 145, 8.42], [145, 146, 4.07], [146, 147, 5.09], [147, 148, 4.99], [148, 149, 2.21], [129, 150, 436.75], [150, 151, 839.4], [151, 152, 176.98], [152, 153, 121.83], [153, 154, 20.29], [154, 155, 48.33], [155, 156, 68.19], [156, 157, 70.76], [157, 158, 77.72], [158, 159, 72.61], [159, 160, 45.44], [160, 161, 20.24], [161, 162, 204.3], [162, 163, 96.87], [163, 164, 3.04], [164, 165, 3.81], [165, 166, 41.16], [166, 167, 24.43], [167, 168, 6.38], [168, 169, 7.63], [169, 170, 84.46], [170, 171, 6.85], [171, 172, 30.84], [172, 173, 104.2], [173, 174, 276.09], [174, 175, 273.77], [175, 176, 98.98], [176, 177, 83.32], [177, 178, 19.85], [178, 179, 8.02], [179, 180, 7.69], [180, 181, 20.49], [181, 182, 30.25], [182, 183, 37.44], [183, 184, 19.71], [184, 185, 7.51], [185, 186, 11.88], [186, 187, 2.82], [187, 188, 4.47], [188, 189, 2.19], [189, 190, 2.62], [190, 191, 4.92], [191, 192, 7.6], [192, 193, 3.7], [193, 194, 3.27], [194, 195, 3.08], [195, 196, 4.83], [196, 197, 4.39], [197, 198, 4.9], [198, 199, 2.76], [199, 200, 2.04], [200, 201, 2.13], [201, 202, 5.42], [202, 203, 6.29], [203, 204, 17.6], [204, 205, 19.89], [205, 206, 11.43], [206, 207, 22.13], [207, 208, 886.71], [208, 209, 41.32], [209, 210, 105.49], [210, 211, 39.02], [211, 212, 8.6], [212, 213, 47.28], [213, 214, 8.48], [214, 215, 73.51], [215, 216, 72.88], [216, 217, 32.34], [217, 218, 162.12], [218, 219, 251.93], [219, 220, 158.97], [220, 221, 3.71], [221, 222, 2.31], [222, 223, 2.95], [223, 224, 20.66], [224, 225, 8.51], [225, 226, 131.79], [226, 227, 10.53], [227, 228, 9.49], [228, 229, 13.84], [229, 230, 8.84], [230, 231, 5.11], [231, 232, 90.42], [232, 233, 4.36], [233, 234, 5.66], [234, 235, 9.51], [235, 236, 8.01], [236, 237, 223.15], [237, 238, 10.01], [238, 239, 21.51], [239, 240, 12.87], [240, 241, 10.18], [241, 242, 332.73], [242, 243, 22.53], [243, 244, 21.53], [244, 245, 6.68], [245, 246, 96.89], [246, 247, 19.17], [247, 248, 75.93], [248, 249, 58.69], [249, 250, 17.81], [250, 251, 12.82], [251, 252, 4.12], [252, 253, 12.8], [253, 254, 2.17], [254, 255, 11.84], [255, 256, 5.23], [256, 28, 5.41], [29, 257, 8.42], [257, 258, 7.03], [258, 259, 8.1], [259, 260, 3.44], [260, 261, 15.1], [261, 262, 4.41], [262, 263, 5.41], [263, 264, 2.55], [264, 265, 3.08], [265, 266, 2.21], [266, 267, 2.5], [267, 268, 2.18], [268, 269, 2.14], [82, 270, 3.13], [270, 271, 22.65], [271, 272, 72.99], [272, 273, 6.45], [273, 274, 2.14], [274, 275, 3.5], [275, 276, 2.36], [276, 277, 2.36], [277, 278, 2.02], [278, 279, 2.02], [279, 280, 10.2], [280, 281, 4.86], [281, 282, 21.15], [282, 283, 14.74], [283, 284, 2.04], [284, 285, 10.38], [285, 286, 4.48], [286, 287, 18.26], [287, 288, 24.42], [288, 289, 32.82], [289, 290, 143.14], [290, 291, 167.97], [291, 292, 4.8], [292, 293, 4.65], [293, 294, 16.3], [294, 295, 8.16], [295, 296, 2.73], [296, 297, 26.25], [297, 298, 5.43], [298, 299, 2.2], [299, 300, 2.7], [300, 301, 4.4], [301, 302, 2.54], [302, 303, 3.21], [303, 304, 3.26], [305, 306, 98.12], [306, 307, 108.14], [307, 308, 135.99], [308, 309, 50.02], [309, 310, 55.42], [310, 311, 21.61], [311, 312, 1158.28], [312, 313, 654.16], [313, 314, 2695.01], [314, 315, 20.87], [315, 125, 6.3], [121, 316, 61.09], [316, 317, 12.25], [317, 318, 30.5], [318, 319, 18.14], [319, 320, 25.81], [320, 321, 4.26], [321, 322, 16.77], [322, 323, 36.77], [323, 110, 22.23], [109, 324, 16.91], [324, 325, 3.59], [325, 326, 4.01], [326, 327, 2.11], [327, 106, 6.66], [105, 328, 2.25], [328, 329, 2.19], [329, 330, 2.03], [330, 331, 2.67], [332, 333, 2.45], [333, 334, 2.54], [334, 335, 2.39], [335, 336, 7.66], [336, 337, 8.15], [337, 338, 24.63], [338, 129, 35.98], [129, 339, 17.56], [339, 340, 1471.34], [340, 341, 149.62], [341, 342, 56.22], [342, 343, 9.98], [343, 344, 9.81], [344, 345, 11.79], [345, 346, 45.68], [346, 347, 15.29], [347, 348, 19.24], [348, 349, 20.18], [349, 350, 173.75], [350, 351, 121.34], [351, 352, 140.22], [352, 353, 18.41], [353, 354, 13.73], [354, 355, 94.3], [355, 356, 21.26], [356, 357, 3.9], [357, 358, 3.69], [334, 130, 165.73], [130, 359, 323.74], [359, 360, 750.03], [360, 361, 2.18], [361, 362, 128.44], [362, 153, 152.89], [179, 363, 4.96], [363, 180, 2.74], [182, 185, 64.66], [247, 364, 72.18], [364, 249, 62.43], [68, 365, 14.43], [365, 366, 10.64], [366, 367, 23.4], [367, 368, 39.66], [368, 369, 19.06], [369, 370, 4.04], [370, 371, 34.68], [371, 372, 6.6], [372, 373, 4.91], [373, 374, 33.92], [374, 375, 29.08], [375, 376, 46.91], [376, 377, 98.34], [377, 378, 5.2], [378, 379, 4.61], [379, 380, 3.12], [380, 381, 3.2], [381, 382, 10.34], [382, 383, 10.35], [383, 384, 4.5], [384, 385, 2.45], [385, 386, 2.79], [386, 387, 3.35], [387, 388, 3.54], [388, 389, 5.83], [389, 390, 6.63], [390, 391, 2.22], [391, 392, 2.1], [129, 393, 25.2], [393, 394, 2.59], [394, 395, 2.79], [395, 396, 5.97], [396, 125, 861.04], [327, 397, 4.21], [397, 398, 4.2], [398, 399, 3.35], [399, 400, 2.31], [400, 104, 3.35], [101, 401, 4.49], [401, 402, 7.09], [402, 98, 2.66], [98, 403, 2.96], [403, 97, 3.52], [87, 404, 148.11], [404, 405, 13.52], [405, 406, 19.59], [406, 407, 6.72], [407, 408, 10.58], [408, 409, 19.98], [409, 410, 7.67], [410, 411, 2.38], [412, 413, 5.96], [413, 414, 42.31], [414, 415, 22.57], [415, 416, 22.13], [416, 417, 52.56], [417, 418, 183.79], [418, 419, 205.05], [419, 420, 198.67], [420, 421, 399.0], [421, 422, 59.86], [422, 423, 383.7], [423, 424, 8.03], [424, 425, 3.02], [425, 426, 2.66], [426, 427, 2.7], [427, 428, 5.29], [428, 429, 3.86], [429, 430, 3.41], [430, 431, 2.42], [431, 432, 2.18], [432, 433, 2.24], [433, 434, 2.57], [434, 435, 2.58], [435, 436, 2.4], [436, 437, 2.26], [437, 438, 2.16], [438, 439, 2.55], [439, 440, 5.15], [440, 441, 4.13], [441, 442, 5.69], [442, 443, 9.32], [443, 444, 50.03], [444, 445, 45.13], [445, 446, 210.4], [446, 447, 20.3], [447, 448, 3.75], [448, 449, 4.87], [449, 450, 2.25], [450, 451, 2.13], [451, 452, 2.96], [452, 453, 2.73], [454, 455, 2.77], [455, 456, 2.35], [456, 457, 4.72], [457, 458, 2.2], [458, 459, 5.64], [459, 460, 44.89], [460, 461, 175.51], [461, 462, 200.85], [462, 463, 1024.6], [463, 464, 28.53], [464, 465, 86.94], [465, 466, 10.01], [466, 467, 143.46], [467, 468, 190.83], [468, 469, 39.67], [469, 470, 61.25], [470, 471, 40.63], [471, 472, 10.11], [472, 473, 15.48], [473, 474, 9.4], [474, 475, 27.18], [475, 476, 29.37], [476, 477, 66.58], [477, 478, 38.31], [478, 479, 68.15], [479, 480, 68.89], [480, 481, 39.8], [481, 94, 7.16], [102, 482, 2.63], [482, 330, 4.7], [483, 484, 9.99], [484, 485, 5.15], [485, 486, 99.3], [486, 487, 4.21], [487, 488, 15.71], [488, 367, 43.39], [365, 489, 4.96], [489, 490, 11.91], [490, 491, 16.4], [491, 492, 7.63], [492, 66, 41.22], [64, 493, 12.14], [493, 62, 2.04], [54, 52, 18.17], [45, 43, 7.3], [41, 494, 15.41], [494, 495, 54.72], [495, 496, 20.9], [496, 497, 19.6], [497, 498, 75.86], [498, 499, 8.94], [499, 500, 6.28], [500, 501, 9.22], [501, 502, 13.39], [502, 503, 30.43], [503, 504, 8.41], [504, 505, 3.29], [505, 506, 10.54], [506, 30, 28.8], [30, 507, 2.33], [507, 508, 16.04], [508, 509, 30.57], [509, 510, 13.13], [510, 511, 10.08], [511, 512, 18.08], [512, 513, 40.36], [513, 514, 119.8], [514, 515, 19.21], [515, 516, 93.33], [516, 517, 25.32], [517, 518, 11.01], [518, 519, 15.25], [519, 520, 15.63], [520, 521, 328.45], [521, 522, 10.07], [522, 523, 12.89], [523, 524, 25.52], [524, 525, 10.01], [525, 526, 223.15], [526, 527, 8.01], [527, 528, 11.01], [528, 529, 6.69], [529, 530, 4.21], [530, 531, 91.34], [531, 532, 4.64], [532, 533, 11.71], [533, 534, 20.96], [534, 535, 12.13], [535, 536, 11.7], [536, 537, 132.45], [537, 538, 29.2], [538, 539, 3.66], [539, 540, 2.43], [540, 541, 2.85], [541, 542, 158.92], [542, 543, 106.75], [543, 544, 2.41], [544, 545, 74.87], [545, 546, 5.1], [546, 547, 373.43], [547, 548, 94.66], [548, 549, 42.7], [549, 550, 3.65], [551, 552, 2.03], [552, 553, 2.12], [553, 554, 2.14], [554, 555, 2.15], [555, 556, 2.12], [556, 557, 2.23], [557, 558, 2.02], [558, 559, 2.01], [559, 560, 2.24], [560, 561, 4.48], [561, 562, 8.59], [562, 563, 8.31], [563, 564, 2.29], [564, 565, 2.82], [565, 566, 5.51], [566, 567, 2.86], [567, 568, 11.32], [568, 569, 3.68], [569, 570, 20.12], [570, 571, 22.86], [571, 572, 51.67], [572, 573, 27.87], [573, 574, 90.99], [574, 575, 15.49], [575, 576, 167.12], [576, 577, 89.46], [577, 578, 89.08], [578, 579, 187.77], [579, 580, 36.56], [580, 581, 40.2], [581, 582, 14.53], [582, 583, 36.0], [583, 584, 26.81], [584, 585, 35.56], [585, 586, 49.27], [586, 587, 38.95], [587, 588, 74.06], [588, 589, 101.11], [589, 590, 19.76], [590, 591, 1499.38], [591, 592, 1793.96], [592, 593, 38.83], [593, 594, 8.36], [594, 595, 52.0], [595, 246, 83.55], [596, 597, 2.15], [597, 598, 8.02], [598, 599, 2.77], [599, 600, 7.52], [600, 601, 42.58], [601, 602, 37.61], [602, 603, 9.73], [603, 604, 24.39], [604, 605, 6.13], [605, 606, 2.06], [606, 607, 7.86], [607, 608, 45.52], [608, 609, 2.97], [609, 610, 6.74], [610, 611, 7.12], [611, 612, 3.1], [612, 613, 224.39], [613, 614, 9.92], [614, 615, 6.8], [615, 616, 129.55], [616, 617, 112.76], [617, 618, 125.07], [618, 619, 23.33], [619, 620, 180.56], [620, 156, 62.73], [37, 621, 6.72], [621, 622, 57.85], [622, 623, 38.69], [623, 624, 3.4], [624, 625, 20.38], [625, 626, 2.0], [626, 627, 6.65], [627, 628, 5.39], [628, 629, 4.78], [629, 630, 3.16], [630, 631, 4.09], [631, 632, 2.85], [632, 633, 2.21], [633, 634, 5.13], [634, 635, 4.52], [635, 636, 4.19], [636, 637, 2.93], [637, 638, 2.69], [638, 639, 5.21], [639, 640, 2.17], [640, 641, 2.53], [641, 642, 2.99], [642, 643, 3.61], [643, 644, 3.12], [644, 645, 4.47], [645, 646, 3.56], [646, 647, 2.12], [542, 218, 252.51], [215, 648, 72.17], [648, 649, 8.57], [649, 650, 44.79], [650, 651, 8.49], [651, 210, 39.16], [208, 652, 368.24], [652, 653, 23.12], [653, 654, 8.12], [654, 655, 6.69], [655, 656, 29.12], [656, 657, 43.79], [657, 658, 9.26], [658, 659, 10.25], [659, 660, 18.49], [660, 661, 5.87], [661, 662, 128.3], [662, 663, 10.66], [663, 664, 5.78], [664, 665, 2.82], [665, 666, 2.41], [666, 667, 4.01], [667, 668, 5.39], [668, 669, 3.5], [669, 670, 3.89], [670, 671, 8.14], [671, 672, 3.21], [672, 673, 2.3], [673, 674, 4.86], [674, 675, 12.1], [675, 676, 8.28], [676, 677, 12.68], [677, 678, 10.89], [678, 679, 6.86], [679, 680, 11.12], [680, 681, 31.5], [681, 682, 7.42], [682, 683, 2.85], [683, 684, 4.63], [684, 685, 2.38], [686, 687, 2.03], [687, 688, 2.41], [688, 689, 3.47], [689, 690, 5.61], [690, 691, 2.24], [691, 692, 2436.98], [692, 305, 156.33], [693, 694, 3.18], [694, 695, 21.45], [695, 696, 2.27], [696, 585, 9.92], [587, 697, 62.84], [697, 698, 123.46], [698, 699, 104.67], [699, 700, 304.34], [700, 701, 504.62], [701, 702, 591.6], [702, 703, 255.5], [703, 704, 1521.62], [704, 705, 107.63], [705, 706, 53.36], [706, 707, 8.61], [707, 708, 113.13], [708, 709, 12.44], [709, 710, 6.37], [710, 711, 154.54], [711, 712, 3.71], [712, 713, 3.67], [713, 714, 32.32], [714, 715, 3.8], [715, 716, 5.47], [716, 42, 64.0], [376, 717, 76.73], [717, 718, 32.48], [718, 719, 56.68], [719, 720, 19.32], [720, 721, 5.69], [721, 722, 13.65], [722, 723, 4.47], [723, 724, 2.94], [724, 725, 19.44], [725, 726, 5.65], [726, 727, 11.54], [727, 728, 25.45], [728, 729, 14.77], [729, 730, 3.1], [730, 731, 3.15], [731, 732, 3.5], [732, 733, 2.38], [733, 734, 22.25], [734, 735, 4.3], [735, 736, 6.4], [736, 737, 2.02], [737, 738, 13.66], [739, 740, 3.11], [740, 741, 3.6], [741, 742, 2.67], [742, 743, 2.64], [743, 744, 6.89], [744, 745, 2.04], [745, 746, 20.63], [746, 747, 15.75], [747, 748, 5.95], [748, 749, 10.6], [749, 750, 28.3], [750, 751, 111.63], [751, 131, 470.11], [131, 752, 3380.0], [752, 753, 102.74], [753, 754, 1088.27], [754, 755, 195.13], [755, 756, 26.77], [756, 757, 76.36], [757, 758, 32.49], [758, 759, 32.73], [759, 760, 20.29], [760, 761, 37.33], [761, 762, 28.03], [762, 763, 5.83], [763, 764, 109.25], [764, 765, 166.88], [765, 766, 75.98], [766, 767, 15.11], [767, 768, 4.12], [768, 769, 2.47], [135, 770, 419.89], [770, 771, 333.91], [771, 772, 195.2], [772, 156, 64.28], [90, 773, 1027.57], [773, 774, 91.3], [774, 775, 447.43], [775, 776, 760.05], [776, 777, 77.36], [777, 778, 46.49], [778, 779, 5.9], [779, 780, 67.67], [780, 781, 2.85], [782, 783, 2.08], [783, 784, 2.03], [784, 785, 3.33], [785, 786, 5.4], [786, 787, 12.13], [787, 788, 11.13], [788, 789, 2.82], [789, 790, 4.92], [790, 791, 9.67], [791, 792, 15.41], [792, 793, 5.81], [793, 794, 2.77], [794, 795, 4.11], [795, 796, 5.59], [796, 797, 6.54], [797, 798, 3.86], [798, 799, 21.29], [799, 800, 22.56], [800, 801, 153.24], [801, 802, 12.54], [802, 803, 89.55], [803, 804, 35.14], [804, 805, 1742.93], [805, 806, 3861.87], [806, 807, 112.89], [807, 808, 920.57], [808, 809, 159.08], [809, 810, 45.95], [810, 811, 67.2], [811, 812, 117.46], [812, 813, 683.76], [813, 814, 1457.75], [814, 815, 12.93], [815, 816, 196.9], [816, 817, 30.21], [817, 818, 142.13], [818, 819, 19.55], [819, 820, 4.42], [820, 821, 3.42], [821, 822, 4.82], [822, 823, 2.18], [823, 824, 3.13], [824, 825, 6.04], [825, 826, 6.03], [826, 827, 3.14], [827, 828, 9.6], [828, 829, 2.34], [829, 830, 3.99], [830, 831, 2.05], [831, 832, 6.03], [832, 833, 3.72], [833, 834, 2.04], [834, 835, 2.07], [835, 836, 2.21], [836, 837, 2.04], [837, 838, 2.04], [314, 839, 3894.46], [839, 840, 1276.45], [840, 841, 1205.09], [841, 842, 355.01], [842, 843, 504.87], [843, 844, 1056.03], [844, 800, 9.87], [786, 845, 3.21], [845, 785, 2.19], [785, 783, 5.18], [846, 847, 2.3], [847, 848, 3.96], [848, 849, 11.47], [849, 850, 18.56], [850, 851, 13.73], [851, 852, 209.05], [852, 853, 42.7], [853, 854, 86.7], [854, 855, 32.34], [855, 856, 189.24], [856, 857, 47.45], [857, 858, 577.91], [858, 859, 33.88], [859, 860, 1614.34], [860, 861, 2112.23], [861, 243, 24.04], [830, 828, 6.33], [828, 826, 12.73], [819, 862, 2.35], [862, 863, 2.61], [863, 818, 14.88], [818, 864, 39.1], [864, 865, 92.24], [865, 866, 112.6], [866, 867, 111.49], [867, 868, 681.29], [868, 869, 35.7], [869, 870, 103.44], [870, 871, 3939.48], [871, 872, 388.24], [872, 873, 21.69], [873, 874, 81.18], [874, 875, 35.66], [875, 876, 3.81], [876, 877, 3.07], [877, 878, 4.02], [878, 879, 2.0], [879, 880, 2.17], [256, 881, 7.58], [881, 882, 2.77], [882, 883, 6.16], [883, 884, 6.99], [884, 885, 3.83], [885, 886, 7.55], [886, 887, 3.64], [887, 888, 2.04], [888, 889, 2.34], [889, 890, 2.44], [890, 891, 2.22], [891, 892, 3.52], [892, 893, 2.67], [893, 894, 2.34], [894, 895, 2.0], [896, 897, 2.65], [897, 898, 5.95], [898, 899, 10.56], [899, 900, 18.82], [900, 901, 2.66], [901, 902, 12.04], [902, 903, 17.53], [903, 904, 58.33], [904, 905, 10.88], [905, 906, 125.45], [906, 907, 19.69], [907, 908, 148.72], [908, 909, 37.82], [909, 910, 248.78], [910, 911, 15.03], [911, 912, 36.13], [912, 209, 11.67], [231, 913, 1803.74], [913, 702, 189.51], [702, 914, 52.85], [914, 915, 93.06], [915, 916, 142.79], [916, 917, 21.19], [917, 918, 34.94], [918, 919, 55.28], [919, 920, 84.61], [920, 921, 19.96], [921, 922, 66.64], [922, 923, 61.47], [923, 924, 66.36], [924, 925, 12.89], [925, 926, 14.32], [926, 927, 17.99], [927, 928, 2.53], [928, 929, 4.29], [929, 930, 2.56], [930, 931, 10.55], [931, 932, 9.27], [932, 933, 6.23], [933, 934, 7.89], [934, 935, 4.37], [935, 936, 7.86], [936, 937, 10.09], [937, 938, 4.89], [938, 939, 3.29], [939, 940, 3.47], [940, 941, 2.97], [941, 942, 9.56], [942, 943, 6.43], [943, 944, 3.25], [944, 945, 3.84], [945, 946, 2.04], [946, 947, 2.68], [947, 948, 2.36], [948, 949, 3.22], [949, 950, 7.51], [950, 951, 2.42], [951, 952, 2.34], [952, 953, 4.07], [953, 954, 6.46], [954, 955, 2.31], [955, 956, 4.7], [956, 957, 4.16], [957, 958, 2.14], [958, 959, 3.29], [959, 960, 2.37], [960, 961, 2.52], [961, 962, 2.16], [962, 963, 2.62], [963, 964, 2.15], [964, 965, 2.94], [965, 966, 2.48], [966, 967, 3.09], [967, 968, 2.93], [968, 969, 2.45], [969, 970, 2.15], [970, 971, 6.4], [971, 972, 3.32], [972, 973, 2.43], [973, 974, 2.97], [974, 975, 4.56], [975, 976, 2.23], [976, 977, 2.39], [977, 978, 4.15], [978, 979, 2.24], [979, 980, 2.61], [980, 981, 3.61], [981, 982, 5.54], [982, 983, 5.04], [983, 984, 2.45], [984, 985, 2.37], [985, 986, 2.73], [986, 987, 2.65], [987, 988, 2.06], [989, 990, 2.63], [990, 991, 14.88], [991, 992, 11.97], [992, 993, 297.97], [993, 994, 6.01], [994, 995, 3.06], [995, 996, 3.7], [996, 997, 2.26], [997, 998, 2.58], [998, 999, 2.07], [999, 1000, 2.5], [1000, 685, 2.1], [684, 1001, 3.36], [1001, 1002, 3.11], [1002, 1003, 6.96], [1003, 1004, 20.06], [1004, 1005, 10.62], [1005, 1006, 5.24], [1006, 1007, 6.21], [1007, 1008, 7.4], [1008, 1009, 11.52], [1009, 676, 12.93], [667, 665, 6.26], [664, 1010, 6.61], [1010, 662, 11.33], [654, 1011, 9.66], [1011, 652, 23.06], [652, 1012, 50.97], [1012, 1013, 42.85], [1013, 1014, 65.54], [1014, 1015, 115.84], [1015, 908, 37.09], [908, 1016, 153.04], [1016, 1017, 21.13], [1017, 1018, 98.97], [1018, 1019, 12.52], [1019, 1020, 8.08], [1020, 1021, 10.96], [1021, 1022, 33.88], [1022, 1023, 19.48], [1023, 1024, 9.39], [1024, 1025, 6.25], [1025, 1026, 7.61], [1026, 1027, 10.68], [1027, 1028, 14.61], [1028, 1029, 5.61], [1029, 1030, 2.27], [1030, 1031, 2.82], [1031, 1032, 2.18], [1032, 1033, 2.29]]


# ══════════════════════════════════════════════════════════════
# BUILD IN-MEMORY GRAPH ON STARTUP
# ══════════════════════════════════════════════════════════════
_NODES = {}   # id → {name, lat, lon, type}
_ADJ   = {}   # id → [(neighbor_id, dist_nm)]

def _build_graph():
    global _NODES, _ADJ
    for row in _GRAPH_NODES:
        nid, name, lat, lon, ntype = row
        _NODES[nid] = {'name': name, 'lat': lat, 'lon': lon, 'type': ntype}
        _ADJ[nid]   = []
    for row in _GRAPH_EDGES:
        f, t, d = row
        _ADJ[f].append((t, d))
        _ADJ[t].append((f, d))

_build_graph()

# ══════════════════════════════════════════════════════════════
# BACKGROUND INIT (land polygons + searoute fallback)
# ══════════════════════════════════════════════════════════════
SR, SR_ERROR, LAND, _init_done = None, None, None, False

def _background_init():
    global SR, SR_ERROR, LAND, _init_done
    try:
        import searoute as sr
        test = sr.searoute([2.35,48.85],[103.82,1.27], units='naut')
        SR   = sr
        print(f'[v12] searoute fallback ready — {test.properties.get("length",0):.0f}NM', flush=True)
    except Exception as e:
        SR_ERROR = str(e)
        print(f'[v12] searoute unavailable: {e}', file=sys.stderr, flush=True)
    try:
        gdf  = gpd.read_file("https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip")
        LAND = gdf.geometry.union_all()
        print('[v12] Land polygons ✅', flush=True)
    except Exception as e:
        print(f'[v12] Land WARNING: {e}', file=sys.stderr, flush=True)
    _init_done = True
    print(f'[v12] Init done — graph: {len(_NODES)} nodes, {len(_GRAPH_EDGES)} edges', flush=True)

threading.Thread(target=_background_init, daemon=True).start()

# ══════════════════════════════════════════════════════════════
# GEOMETRY
# ══════════════════════════════════════════════════════════════
def haversine(lat1, lon1, lat2, lon2):
    R    = 3440.065
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a    = (math.sin(dlat/2)**2 +
            math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*
            math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, a)))

def bearing(lon1, lat1, lon2, lat2):
    dlon  = math.radians(lon2-lon1)
    la, lb = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon)*math.cos(lb)
    y = math.cos(la)*math.sin(lb) - math.sin(la)*math.cos(lb)*math.cos(dlon)
    return (math.degrees(math.atan2(x,y))+360) % 360

def segment_crosses_land(c1, c2):
    if LAND is None: return False
    try:   return LineString([c1,c2]).intersects(LAND)
    except: return False

def any_land(coords):
    return any(segment_crosses_land(coords[i],coords[i+1])
               for i in range(len(coords)-1))

# ══════════════════════════════════════════════════════════════
# GRAPH ROUTING — A* on PortToPort waypoint graph
# ══════════════════════════════════════════════════════════════
def nearest_graph_nodes(lat, lon, k=5):
    """Find k nearest graph nodes to a coordinate."""
    dists = [(haversine(lat,lon,nd['lat'],nd['lon']), nid)
             for nid, nd in _NODES.items()]
    dists.sort()
    return dists[:k]

def astar(start_id, end_id):
    """A* shortest path through the waypoint graph."""
    end_lat = _NODES[end_id]['lat']
    end_lon = _NODES[end_id]['lon']

    def h(nid):
        return haversine(_NODES[nid]['lat'], _NODES[nid]['lon'], end_lat, end_lon)

    g      = {nid: float('inf') for nid in _NODES}
    g[start_id] = 0
    prev   = {}
    pq     = [(h(start_id), 0.0, start_id)]
    vis    = set()

    while pq:
        f, cost, u = heapq.heappop(pq)
        if u in vis: continue
        vis.add(u)
        if u == end_id: break
        for v, w in _ADJ.get(u, []):
            nc = cost + w
            if nc < g[v]:
                g[v]   = nc
                prev[v] = u
                heapq.heappush(pq, (nc + h(v), nc, v))

    if g[end_id] == float('inf'):
        return None, float('inf')   # no path found

    path, cur = [], end_id
    while cur in prev:
        path.append(cur)
        cur = prev[cur]
    path.append(start_id)
    return list(reversed(path)), g[end_id]

def build_route_graph(from_lat, from_lon, to_lat, to_lon):
    """
    Main routing function using PortToPort graph.
    Tries multiple start/end node combinations and picks best path.
    """
    from_candidates = nearest_graph_nodes(from_lat, from_lon, k=3)
    to_candidates   = nearest_graph_nodes(to_lat,   to_lon,   k=3)

    best_path, best_dist = None, float('inf')
    best_start, best_end = None, None

    for d1, n1 in from_candidates:
        for d2, n2 in to_candidates:
            if n1 == n2: continue
            path, dist = astar(n1, n2)
            if path and dist < best_dist:
                # Add access legs: origin → first node, last node → dest
                total = d1 + dist + d2
                if total < best_dist:
                    best_dist  = total
                    best_path  = path
                    best_start = n1
                    best_end   = n2

    if best_path is None:
        return None, None, float('inf'), 'graph-no-path'

    # Build coordinate list
    coords = [[from_lon, from_lat]]   # origin
    for nid in best_path:
        nd = _NODES[nid]
        coords.append([nd['lon'], nd['lat']])
    coords.append([to_lon, to_lat])   # destination

    return coords, best_path, best_dist, 'graph-astar'

def build_route_searoute_fallback(from_lat, from_lon, to_lat, to_lon):
    """Fallback to searoute when graph has no path."""
    if SR is None:
        return [[from_lon,from_lat],[to_lon,to_lat]], 0, 'direct-fallback'
    try:
        r = SR.searoute([from_lon,from_lat],[to_lon,to_lat],
                        units='naut', append_orig_dest=True)
        coords  = r.geometry['coordinates']
        dist_nm = float(r.properties.get('length',0))
        return coords, dist_nm, 'searoute-fallback'
    except Exception as e:
        return [[from_lon,from_lat],[to_lon,to_lat]], 0, f'fallback-error:{e}'

# ══════════════════════════════════════════════════════════════
# SIMPLIFICATION — RDP algorithm
# ══════════════════════════════════════════════════════════════
def rdp_simplify(coords, epsilon_nm=2.0):
    if len(coords) <= 2: return coords
    def pt_dist(p, a, b):
        dx,dy = b[0]-a[0], b[1]-a[1]
        if dx==dy==0: return haversine(p[1],p[0],a[1],a[0])
        t = max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
        return haversine(p[1],p[0], a[1]+t*dy, a[0]+t*dx)
    def rdp(pts, eps):
        if len(pts)<=2: return pts
        dmax,idx = 0,0
        for i in range(1,len(pts)-1):
            d = pt_dist(pts[i], pts[0], pts[-1])
            if d > dmax: dmax,idx = d,i
        if dmax > eps:
            return rdp(pts[:idx+1],eps)[:-1] + rdp(pts[idx:],eps)
        return [pts[0], pts[-1]]
    return rdp(coords, epsilon_nm)

# ══════════════════════════════════════════════════════════════
# SAFETY CHECKS
# ══════════════════════════════════════════════════════════════
GEBCO_API    = "https://api.odb.ntu.edu.tw/gebco"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
DANGER_TYPES = ['rock','wreck','obstruction','shoal','reef',
                'underwater_rock','foul_ground','snag']
_dcache, _tcache = {}, {}

def query_tss_osm(coords, buf=0.3):
    if not coords: return []
    lons=[c[0] for c in coords]; lats=[c[1] for c in coords]
    s,n,w,e = round(min(lats)-buf,2),round(max(lats)+buf,2),\
              round(min(lons)-buf,2),round(max(lons)+buf,2)
    key=f"{s}_{w}_{n}_{e}"
    if key in _tcache: return _tcache[key]
    q=f"""[out:json][timeout:20];
(way["seamark:type"="separation_lane"]({s},{w},{n},{e});
 way["seamark:type"="separation_zone"]({s},{w},{n},{e});
 relation["seamark:type"="traffic_separation_scheme"]({s},{w},{n},{e}););
out tags center;"""
    zones=[]
    try:
        r=requests.post(OVERPASS_API,data={'data':q},timeout=15)
        if r.status_code==200:
            for el in r.json().get('elements',[]):
                t=el.get('tags',{})
                nm=t.get('seamark:name') or t.get('name') or 'TSS'
                if nm not in zones: zones.append(nm)
    except: pass
    _tcache[key]=zones; return zones

def check_dangers(coords, buf_nm=2.0):
    lons=[c[0] for c in coords]; lats=[c[1] for c in coords]
    s,n,w,e = round(min(lats)-.1,2),round(max(lats)+.1,2),\
              round(min(lons)-.1,2),round(max(lons)+.1,2)
    key=f"{s}_{w}_{n}_{e}"
    if key in _dcache: dm=_dcache[key]
    else:
        fi='\n'.join([f'  node["seamark:type"="{t}"]({s},{w},{n},{e});' for t in DANGER_TYPES])
        q=f"[out:json][timeout:20];\n(\n{fi}\n);\nout body;"
        dm=[]
        try:
            r=requests.post(OVERPASS_API,data={'data':q},timeout=15)
            if r.status_code==200:
                for el in r.json().get('elements',[]):
                    tags=el.get('tags',{})
                    dm.append({'type':tags.get('seamark:type','?'),
                               'name':tags.get('name',''),
                               'lon':el.get('lon'),'lat':el.get('lat')})
        except: pass
        _dcache[key]=dm
    nearby=[]
    for d in dm:
        dl,da=d.get('lon'),d.get('lat')
        if dl is None: continue
        md=min(haversine(da,dl,c[1],c[0]) for c in coords)
        if md<buf_nm: nearby.append({**d,'nearest_nm':round(md,2)})
    return {'safe':len(nearby)==0,'dangers':nearby,'total':len(dm)}

def check_depth(coords, draft=10.0, safety=2.0):
    mr=draft+safety
    pts=[]
    for i in range(len(coords)-1):
        c1,c2=coords[i],coords[i+1]
        nm=haversine(c1[1],c1[0],c2[1],c2[0])
        st=max(1,int(nm/15))
        for s in range(st):
            t=s/st; pts.append((c1[0]+t*(c2[0]-c1[0]),c1[1]+t*(c2[1]-c1[1])))
    if coords: pts.append((coords[-1][0],coords[-1][1]))
    shallow,depths=[],[]
    try:
        lons=[str(round(p[0],4)) for p in pts]
        lats=[str(round(p[1],4)) for p in pts]
        r=requests.get(f"{GEBCO_API}?lon={','.join(lons)}&lat={','.join(lats)}&mode=zonly",timeout=15)
        if r.status_code==200:
            data=r.json(); zs=data.get('z',[]) if isinstance(data,dict) else data
            for i,p in enumerate(pts):
                if i<len(zs) and zs[i] is not None:
                    wd=abs(zs[i]) if zs[i]<0 else 0
                    depths.append(wd)
                    if 0<wd<mr: shallow.append({'lon':p[0],'lat':p[1],'depth':round(wd,1),'required':mr})
    except: pass
    return {'safe':len(shallow)==0,'min_depth':round(min(depths),1) if depths else None,
            'shallow':shallow,'checked':len(pts),'required':mr}

# ══════════════════════════════════════════════════════════════
# GET /route
# ══════════════════════════════════════════════════════════════
@app.route('/route')
def route():
    try:
        from_lat = float(request.args['fromLat'])
        from_lon = float(request.args['fromLon'])
        to_lat   = float(request.args['toLat'])
        to_lon   = float(request.args['toLon'])
        draft    = float(request.args.get('draft',  10.0))
        safety   = float(request.args.get('safety',  2.0))
        eps      = float(request.args.get('simplify', 2.0))
    except (KeyError,ValueError) as e:
        return jsonify({'error':f'Bad param: {e}'}), 400

    # ── Graph routing ──────────────────────────────────────────
    coords, path, graph_nm, method = build_route_graph(
        from_lat, from_lon, to_lat, to_lon
    )

    if coords is None:
        # Fallback
        coords, graph_nm, method = build_route_searoute_fallback(
            from_lat, from_lon, to_lat, to_lon
        )
        path = []

    # ── Simplify ───────────────────────────────────────────────
    simplified = rdp_simplify(coords, epsilon_nm=eps)

    # ── Recalc NM ─────────────────────────────────────────────
    total_nm = sum(
        haversine(simplified[i][1],simplified[i][0],
                  simplified[i+1][1],simplified[i+1][0])
        for i in range(len(simplified)-1)
    )

    # ── Land check ────────────────────────────────────────────
    land_cross = any_land(simplified)

    # ── Named waypoints on route ──────────────────────────────
    named_wps = []
    if path:
        for nid in path:
            nd = _NODES[nid]
            if nd['name']:
                named_wps.append({
                    'name': nd['name'],
                    'lat':  nd['lat'],
                    'lon':  nd['lon'],
                    'type': nd['type']
                })

    # ── TSS / Danger / Depth ─────────────────────────────────
    tss    = query_tss_osm(simplified)
    danger = check_dangers(simplified)
    depth  = check_depth(simplified, draft, safety)

    warnings = []
    if land_cross:
        warnings.append('🚨 Route crosses land')
    for z in tss:
        warnings.append(f'🚢 TSS zone: {z}')
    for sp in depth.get('shallow',[]):
        warnings.append(f"⚠️ Shallow {sp['depth']}m at ({sp['lat']:.3f},{sp['lon']:.3f})")
    for d in danger.get('dangers',[]):
        warnings.append(f"🪨 {d['type']} '{d['name']}' {d['nearest_nm']}NM from route")

    overall_safe = not land_cross and depth['safe'] and danger['safe']

    print(f'[route] {total_nm:.0f}NM | {len(coords)}→{len(simplified)}pts '
          f'| method={method} | named_wps={len(named_wps)} | land={land_cross}', flush=True)

    return jsonify({
        'waypoints':    [{'lat':float(c[1]),'lon':float(c[0])} for c in simplified],
        'namedWaypoints': named_wps,
        'totalNM':      round(total_nm,1),
        'source':       'maritime-router-v12',
        'method':       method,
        'graphNodes':   len(_NODES),
        'graphEdges':   len(_GRAPH_EDGES),
        'pointsRaw':    len(coords),
        'pointsFinal':  len(simplified),
        'landCrossing': land_cross,
        'tssZones':     tss,
        'overallSafe':  overall_safe,
        'warnings':     warnings,
        'safetyReport': {'depth':depth,'danger':danger},
    })

# ══════════════════════════════════════════════════════════════
# POST /safety-check
# ══════════════════════════════════════════════════════════════
@app.route('/safety-check', methods=['POST','OPTIONS'])
def safety_check():
    if request.method=='OPTIONS': return jsonify({}),200
    try:
        body=request.get_json(force=True)
        if not body: return jsonify({'error':'JSON required'}),400
        raw=body.get('waypoints',[])
        if len(raw)<2: return jsonify({'error':'Need ≥2 waypoints'}),400
        coords=[[float(w['lon']),float(w['lat'])] for w in raw]
        draft =float(body.get('draft', 10.0))
        safety=float(body.get('safety', 2.0))
        beam  =float(body.get('beam',  32.0))
        loa   =float(body.get('loa',  200.0))

        land_cross=any_land(coords)
        land_segs=[]
        if land_cross:
            for i in range(len(coords)-1):
                if segment_crosses_land(coords[i],coords[i+1]):
                    land_segs.append({'from':{'lon':coords[i][0],'lat':coords[i][1]},
                                      'to':{'lon':coords[i+1][0],'lat':coords[i+1][1]},'seg':i})

        tss   =query_tss_osm(coords)
        depth =check_depth(coords,draft,safety)
        danger=check_dangers(coords)

        total_nm,max_leg,legs=0.0,0.0,[]
        for i in range(len(coords)-1):
            c1,c2=coords[i],coords[i+1]
            nm=haversine(c1[1],c1[0],c2[1],c2[0])
            total_nm+=nm; max_leg=max(max_leg,nm)
            legs.append({'from':{'lon':c1[0],'lat':c1[1]},'to':{'lon':c2[0],'lat':c2[1]},
                         'nm':round(nm,1),'bearing':round(bearing(c1[0],c1[1],c2[0],c2[1]),1)})

        warnings=[]
        if land_cross: warnings.append(f'🚨 LAND CROSSING {len(land_segs)} segment(s)')
        for z in tss:   warnings.append(f'🚢 TSS: {z}')
        for sp in depth.get('shallow',[]): warnings.append(f"⚠️ Shallow {sp['depth']}m")
        for d in danger.get('dangers',[]): warnings.append(f"🪨 {d['type']} {d['nearest_nm']}NM")

        eta=lambda nm,kn: round(nm/kn,2) if kn>0 else None
        overall=not land_cross and depth['safe'] and danger['safe']

        return jsonify({
            'overall_safe':overall,'total_warnings':len(warnings),'warnings':warnings,
            'route_stats':{'total_nm':round(total_nm,1),'waypoint_count':len(coords),
                           'max_leg_nm':round(max_leg,1),
                           'eta':{'10kn':eta(total_nm,10),'12kn':eta(total_nm,12),
                                  '14kn':eta(total_nm,14),'15kn':eta(total_nm,15),'18kn':eta(total_nm,18)}},
            'land_check':{'safe':not land_cross,'problem_segments':land_segs},
            'tss_check':{'zones_found':len(tss),'zones':tss},
            'depth_check':{'safe':depth['safe'],'min_depth_m':depth.get('min_depth'),
                           'required_depth':depth.get('required'),'shallow':depth.get('shallow',[])},
            'danger_check':{'safe':danger['safe'],'dangers':danger.get('dangers',[])},
            'vessel_params':{'draft_m':draft,'safety_m':safety,'beam_m':beam,'loa_m':loa},
            'legs':legs,
        })
    except Exception as e:
        print(f'[safety-check] {e}',file=sys.stderr)
        return jsonify({'error':str(e)}),500

# ══════════════════════════════════════════════════════════════
# GET /health  GET /graph/stats
# ══════════════════════════════════════════════════════════════
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        'status':    'ok',
        'service':   'maritime-router v12',
        'arch':      'porttoport-graph-astar',
        'graph':     {'nodes':len(_NODES),'edges':len(_GRAPH_EDGES)},
        'land':      LAND is not None,
        'searoute':  SR is not None,
        'init_done': _init_done,
    })

@app.route('/graph/stats')
def graph_stats():
    named  = [nd for nd in _NODES.values() if nd['name']]
    types  = {}
    for nd in _NODES.values():
        types[nd['type']] = types.get(nd['type'],0)+1
    return jsonify({
        'total_nodes': len(_NODES),
        'total_edges': len(_GRAPH_EDGES),
        'named_nodes': len(named),
        'node_types':  types,
        'key_waypoints': [
            {'name':nd['name'],'lat':nd['lat'],'lon':nd['lon'],'type':nd['type']}
            for nd in named
            if nd['type'] in ['canal','strait','headland','corridor','pilot_station']
        ]
    })

# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f'[v12] Starting on port {port} — graph: {len(_NODES)} nodes', flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
