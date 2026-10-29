import json,tempfile,unittest
from pathlib import Path
from pr_controller import PremiereController,Config,NativeError
from pr_controller.client import frame_ticks
from pr_controller.subtitles import Cue,parse,render,shift,seconds
from pr_controller.recipes import photo_wall,page_fan

class ExtendedTests(unittest.TestCase):
    def test_fractional_frame_ticks(self):
        self.assertEqual(frame_ticks(1,'30000/1001'),'8475667200')
    def test_invalid_timestamp_and_nan(self):
        with self.assertRaises(ValueError):seconds('00:60:00.000')
        with self.assertRaises(ValueError):render([Cue(float('nan'),3,'bad')])
    def test_vtt_short_timestamp_and_settings(self):
        cues=parse('WEBVTT\n\n00:01.000 --> 00:02.000 align:start\nHello\n')
        self.assertEqual(cues[0].settings,'align:start')
        self.assertEqual(parse(render(shift(cues,1),'vtt'))[0].start,2)
    def test_wall_many_photos_positive_bounds(self):
        self.assertTrue(all(min(x['box'])>0 for x in photo_wall(list(range(37)),49)))
        with self.assertRaises(ValueError):page_fan([])
    def test_queued_cancel_is_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            c=PremiereController(config=Config(runtime=Path(directory)))
            ident=c.submit('timeline',{})
            c.cancel_queued(ident)
            self.assertEqual(c.job_status(ident)['state'],'cancelled')
            self.assertTrue(c.job_status(ident)['complete'])
    def test_reject_bad_job_identifier(self):
        with self.assertRaises(ValueError):PremiereController().job_status('../secret')
    def test_transition_option_forwarded(self):
        c=PremiereController();captured=[]
        def edit(op,args,**kwargs):captured.append((op,args,kwargs));return {}
        c._edit=edit
        c.clone_or_move(0,0,1,copy_transitions=False)
        self.assertFalse(captured[0][1]['copy_transitions'])
        self.assertTrue(captured[0][2]['transactional'])
    def test_caption_registry_and_export(self):
        from pr_controller.caption_sources import register,export
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);c=PremiereController(config=Config(runtime=root/'runtime'))
            c.invoke=lambda op,**args: {'id':'fixture-sequence','name':'Fixture','index':0}
            source=root/'source.srt';source.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n',encoding='utf-8')
            data=register(c,source,offset=2);out=root/'shifted.md';export(c,data['id'],out,format='md',delta=3)
            self.assertEqual(parse(out.read_text())[0].start,6)
    def test_optional_photo_card(self):
        try:from PIL import Image
        except ImportError:self.skipTest('Install visual extra')
        from pr_controller.visual import photo_card
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'original.png';Image.new('RGB',(80,60),'red').save(source);before=source.read_bytes()
            result=photo_card(source,root/'card.png')
            self.assertEqual(source.read_bytes(),before)
            self.assertGreater(result['width'],80)
            with self.assertRaises(FileExistsError):photo_card(source,source)

if __name__=='__main__':unittest.main()
