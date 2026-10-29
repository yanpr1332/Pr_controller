import unittest,tempfile,json,threading,time
from pathlib import Path
from pr_controller import PremiereController,Config,NativeError
from pr_controller.client import ticks
from pr_controller.subtitles import Cue,parse,render,shift
class CoreTests(unittest.TestCase):
    def test_ticks(self):
        self.assertEqual(ticks(1/30),'8467200000')
        with self.assertRaises(ValueError):ticks(float('nan'))
    def test_constructor_no_install(self):
        with tempfile.TemporaryDirectory() as d:
            c=PremiereController(config=Config(Path(d)/'missing.exe',Path(d)/'runtime'))
            self.assertFalse(c.runtime.exists())
    def test_complete_protocol_multiline(self):
        with tempfile.TemporaryDirectory() as d:
            c=PremiereController(config=Config(Path(d)/'x',Path(d)))
            def worker():
                while not list(Path(d).glob('*.job.json')):time.sleep(.01)
                f=next(Path(d).glob('*.job.json'));job=json.loads(f.read_text());r={'id':job['id'],'complete':True,'ok':True,'data':'中文\nsecond|line'}
                tmp=Path(d)/'reply.tmp';tmp.write_text(json.dumps(r),encoding='utf-8');tmp.replace(Path(d)/(job['id']+'.result.json'))
            t=threading.Thread(target=worker,daemon=True);t.start();self.assertEqual(c._request('x',{},2),'中文\nsecond|line');t.join()
    def test_timeout_retains_job(self):
        with tempfile.TemporaryDirectory() as d:
            c=PremiereController(config=Config(Path(d)/'x',Path(d)))
            with self.assertRaises(TimeoutError):c._request('x',{},.01)
            self.assertEqual(len(list(Path(d).glob('*.job.json'))),1)
    def test_restart_disabled(self):
        with self.assertRaises(ValueError):PremiereController().run([],restart=True)
    def test_subtitle_roundtrip(self):
        cues=[Cue(1,2,'First\nline'),Cue(3,5,'Next')]
        for fmt in ('vtt','srt','md'):self.assertEqual(parse(render(cues,fmt)),cues)
        self.assertEqual(shift(cues,2,3)[1].start,5)
    def test_subtitle_bad_overlap(self):
        with self.assertRaises(ValueError):render([Cue(0,3,'a'),Cue(2,4,'b')])
    def test_arguments(self):
        with self.assertRaises(ValueError):PremiereController().place_media('x',0,source_in=2,source_out=1)
        with self.assertRaises(ValueError):PremiereController().fit_clip(0,0,source_width=0,source_height=1)
    def test_recipes(self):
        from pr_controller.recipes import photo_wall,page_fan,fade
        self.assertEqual(len(photo_wall(['a','b','c'],5)),3)
        self.assertEqual(page_fan(['a','b','c'])[1]['rotation'],0)
        with self.assertRaises(ValueError):fade(.2,.4,.4)
    def test_collect_same_names(self):
        from pr_controller.media import collect
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').mkdir();(p/'b').mkdir();(p/'a'/'x.txt').write_text('a');(p/'b'/'x.txt').write_text('b')
            timeline={'video':[{'clips':[{'path':str(p/'a'/'x.txt')},{'path':str(p/'b'/'x.txt')}]}]}
            r=collect([timeline],p/'out',dry_run=False)
            self.assertEqual(len(set(x['relative'] for x in r['files'])),2)
            with self.assertRaises(FileExistsError):collect([timeline],p/'out',dry_run=False)
if __name__=='__main__':unittest.main()
