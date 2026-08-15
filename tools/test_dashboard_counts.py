import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dbdata import scum_db

print("Fahrzeuge:", scum_db.get_vehicle_count())
print("Basen:", scum_db.get_base_count())
print("Wetter:", scum_db.get_weather())
