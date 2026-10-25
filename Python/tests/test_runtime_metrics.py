import unittest
from suika_ai.video_viewer import FrameMetrics
class RuntimeMetricsTests(unittest.TestCase):
    def test_stale_frame_age_distinguished_from_new_frame_latency(self):
        m=FrameMetrics();m.add(1,12,3,1);m.transfer.append(4)
        m.observe(1,12,.1);m.observe(2,1012,.1)
        r=m.result(2)
        self.assertEqual(r['displayed'],1);self.assertEqual(r['capture_to_tk_submit_ms']['maximum'],12)
        self.assertEqual(r['held_frame_age_ms']['maximum'],1012);self.assertEqual(r['viewer_poll_gaps_ms']['maximum'],1000)
    def test_diagnostic_arrays_bounded(self):
        m=FrameMetrics()
        for i in range(5000):m.observe(i,20,.1)
        self.assertEqual(len(m.ages),4096);self.assertEqual(len(m.poll_gaps),4096)
