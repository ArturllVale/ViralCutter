import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.generate_premiere_xml import create_premiere_xml as create_single_premiere_xml
from scripts.export_xml_lib.xml_generator import create_premiere_xml as create_export_premiere_xml

class TestPremiereStructure(unittest.TestCase):
    def test_single_premiere_xml_structure(self):
        xml = create_single_premiere_xml(
            project_name='TestProj1',
            video_path='/path/to/video.mp4',
            overlay_path=None,
            duration_frames=300,
            width=1080,
            height=1920,
            timebase=30,
            face_data=[{'frame': 0, 'faces': [[100, 100, 300, 300]]}],
            source_width=1920,
            source_height=1080
        )
        self.assertIn('<xmeml version="4">', xml)
        self.assertIn('<name>TestProj1</name>', xml)
        self.assertIn('<width>1080</width>', xml)
        self.assertIn('<height>1920</height>', xml)
        self.assertIn('<duration>300</duration>', xml)
        self.assertIn('<keyframe>', xml)

    def test_export_premiere_xml_dual_track(self):
        face_data = [
            {'frame': 0, 'faces': [[100, 50, 200, 150], [600, 50, 700, 150]]},
            {'frame': 15, 'faces': [[105, 52, 205, 152], [595, 48, 695, 148]]}
        ]
        xml = create_export_premiere_xml(
            project_name='DualTrackTest',
            video_path='/path/to/video.mp4',
            overlay_segments=[],
            duration_frames=150,
            width=1080,
            height=1920,
            timebase=30,
            scale_value=100.0,
            face_data=face_data,
            source_width=1920,
            source_height=1080
        )
        self.assertIn('<xmeml version="4">', xml)
        self.assertIn('<name>DualTrackTest_CutRef</name>', xml)
        self.assertIn('<track>', xml)
        self.assertIn('<duration>150</duration>', xml)

if __name__ == '__main__':
    unittest.main()
