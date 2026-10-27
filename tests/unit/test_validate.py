import copy
import unittest
from src.heyaa.edl.schema import EDLValidationError
from src.heyaa.edl.validate import validate_edl

def sample():
    return {"version":1,"fps_num":30,"fps_den":1,"width":1080,"height":1920,"total_frames":60,
      "video":[{"type":"clip","source":"in.mp4","source_start_f":0,"source_dur_f":30,"start_f":0,"dur_f":30,"speed":1.0,"crop":{"x":0,"y":0,"w":1,"h":1}},
               {"type":"freeze","source":"in.mp4","source_frame_f":29,"start_f":30,"dur_f":30,"effect":"phonk-freeze"}],
      "audio":[{"source":"song.wav","source_start_f":0,"start_f":0,"dur_f":60,"gain_db":-1.0}]}

class ValidateTests(unittest.TestCase):
    def test_valid(self):
        edl=sample(); self.assertIs(validate_edl(edl),edl)
    def test_unknown_field(self):
        e=sample(); e["mystery"]=1
        with self.assertRaisesRegex(EDLValidationError,"unknown field"): validate_edl(e)
    def test_gaps_and_overlaps(self):
        for start in (29,31):
            e=sample(); e["video"][1]["start_f"]=start
            with self.assertRaises(EDLValidationError): validate_edl(e)
    def test_total_mismatch(self):
        e=sample(); e["total_frames"]=59
        with self.assertRaisesRegex(EDLValidationError,"total_frames"): validate_edl(e)
    def test_bad_crop_and_speed(self):
        e=sample(); e["video"][0]["crop"]["x"]=0.5
        with self.assertRaises(EDLValidationError): validate_edl(e)
        e=sample(); e["video"][0]["speed"]=8
        with self.assertRaises(EDLValidationError): validate_edl(e)
    def test_audio_bounds(self):
        e=sample(); e["audio"][0]["dur_f"]=61
        with self.assertRaises(EDLValidationError): validate_edl(e)
    def test_bool_is_not_integer(self):
        e=sample(); e["total_frames"]=True
        with self.assertRaises(EDLValidationError): validate_edl(e)
    def test_required_fps_den_and_clip_speed(self):
        e = sample()
        del e["fps_den"]
        with self.assertRaises(EDLValidationError):
            validate_edl(e)
        e = sample()
        del e["video"][0]["speed"]
        with self.assertRaises(EDLValidationError):
            validate_edl(e)

    def test_no_mutation(self):
        e=sample(); before=copy.deepcopy(e); validate_edl(e); self.assertEqual(e,before)

if __name__ == "__main__": unittest.main()
