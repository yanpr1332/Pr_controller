"""Opt-in integration checks. Uses a fresh project and synthetic media only."""
import argparse,json,sys,time,uuid
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pr_controller import PremiereController,Config,NativeError

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--workspace',required=True);p.add_argument('--media-directory',required=True);p.add_argument('--preset');p.add_argument('--visual',action='store_true');a=p.parse_args()
    workspace_base=Path(a.workspace).resolve();workspace_base.mkdir(parents=True,exist_ok=True)
    workspace=workspace_base/('run_'+uuid.uuid4().hex[:8]);workspace.mkdir()
    c=PremiereController(config=Config(runtime=Path(a.runtime)))
    current=c.invoke('eval',source="String(app.project.path||'')")
    if current and not Path(current).resolve().is_relative_to(workspace_base):raise RuntimeError('Close the non-test project before integration testing')
    def semantic(value):
        if isinstance(value,dict):return {k:semantic(v) for k,v in value.items() if k not in ('id','clipId','nodeId')}
        if isinstance(value,list):return [semantic(v) for v in value]
        return value
    results=[]
    def record(name,value=True):
        results.append({'case':name,'passed':bool(value)});print(name,'PASS' if value else 'FAIL',flush=True)
        (workspace/'native_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        if not value:raise AssertionError(name)
    project=workspace/('Smoke_'+uuid.uuid4().hex[:8]+'.prproj')
    c.new_project(str(project));media=Path(a.media_directory).resolve()
    c.import_files([str(media/'dev_video.mp4'),str(media/'dev_audio.wav')]);c.create_sequence_from_clips('Smoke_Main',['dev_video.mp4'])
    st=c.configure_sequence('Smoke_Main',width=1920,height=1080,fps=30);record('sequence settings',st['width']==1920 and st['height']==1080 and st['fps']==30)
    c.move_linked_av(2);record('linked AV movement',c.timeline('Smoke_Main')['video'][0]['clips'][0]['start']==2)
    c.add_video_effect('Crop',sequence='Smoke_Main')
    components=c.inspect_native(0,0,sequence='Smoke_Main');record('gap-aware localized effect insertion',len(components)>2)
    c.animate(0,0,[{'component':'AE.ADBE Opacity','index':0,'keys':[{'seconds':0,'value':0},{'seconds':1,'value':100}]}],sequence='Smoke_Main',ease=True)
    r=c.clone_or_move(0,0,1,sequence='Smoke_Main');record('strict FX/keyframe video clone',r['destination']['start']==2 and not r['sourceRemoved'])
    r=c.clone_av(0,0,2,2,sequence='Smoke_Main');record('linked AV clone',r['video']['destination']['start']==2 and r['audio']['destination']['start']==2)
    before=c.timeline('Smoke_Main');c.ensure_tracks(4,4,sequence='Smoke_Main');after=c.timeline('Smoke_Main')
    record('appended tracks preserve indices',before['video'][0]['clips']==after['video'][0]['clips'])
    c.place_media(str(media/'dev_audio.wav'),12,source_out=1,media='audio',audio_track=1,sequence='Smoke_Main');record('audio placement')
    before=c.timeline('Smoke_Main')['audio'];c.place_media(str(media/'dev_video.mp4'),16,source_out=1,media='video',video_track=3,sequence='Smoke_Main');record('video-only leaves all audio untouched',semantic(before)==semantic(c.timeline('Smoke_Main'))['audio'])
    before=c.timeline('Smoke_Main')['video'];c.place_media(str(media/'dev_video.mp4'),18,source_out=1,media='audio',audio_track=3,sequence='Smoke_Main');record('audio-only leaves all video untouched',semantic(before)==semantic(c.timeline('Smoke_Main'))['video'])
    original=c.timeline('Smoke_Main');c.shift_timeline(12,1,sequence='Smoke_Main',dry_run=True);record('shift dry run has no side effects',original==c.timeline('Smoke_Main'))
    c.shift_timeline(12,1,sequence='Smoke_Main',dry_run=False);record('shift apply',c.timeline('Smoke_Main')['audio'][1]['clips'][0]['start']==13)
    before=c.timeline('Smoke_Main')
    try:c.clone_or_move(0,0,1,sequence='Smoke_Main',move=True)
    except NativeError:pass
    else:raise AssertionError('Expected occupied-track rejection')
    record('failed move restores project',semantic(before)==semantic(c.timeline('Smoke_Main')))
    before=c.timeline('Smoke_Main')
    try:c.transaction([{'operation':'props','args':{'sequence':'Smoke_Main','kind':'video','track':0,'clip':0,'properties':[{'component':'AE.ADBE Motion','index':1,'value':81}]}},{'operation':'props','args':{'sequence':'Smoke_Main','kind':'video','track':0,'clip':0,'properties':[{'component':'missing','index':0,'value':1}]}}])
    except NativeError:pass
    else:raise AssertionError('Expected transaction failure')
    record('multi-action rollback',semantic(before)==semantic(c.timeline('Smoke_Main')))
    response=c.invoke('eval',source="({text:'中文'+String.fromCharCode(10)+'line|x',hasOwnProperty:'data',control:String.fromCharCode(8)})")
    record('structured unicode/control characters',response['text']=='中文\nline|x' and response['control']=='\b')
    c.preview(workspace/'preview',2.5,sequence='Smoke_Main');record('PNG preview',(workspace/'preview.png').is_file())
    subtitle=workspace/'test.srt';subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\nTest caption\n',encoding='utf-8')
    registered=c.register_subtitle_source(subtitle,sequence='Smoke_Main',import_track=True)
    c.export_subtitle_source(registered['id'],workspace/'exported.vtt',sequence='Smoke_Main',delta=1)
    record('registered captions import and shifted export','00:00:02.000' in (workspace/'exported.vtt').read_text())
    r=c.clone_group([0],3,sequence='Smoke_Main',source_track=0,target_audio_track=3,move=True)
    record('atomic linked group move',r['sourceRemoved'] and not c.timeline('Smoke_Main')['video'][0]['clips'] and not c.timeline('Smoke_Main')['audio'][0]['clips'])
    c.add_marker(13,'Shift marker');c.shift_timeline(13,1,sequence='Smoke_Main',dry_run=False)
    record('markers follow timeline shift',any(m['name']=='Shift marker' and abs(m['start']-14)<1e-6 for m in c.timeline('Smoke_Main')['markers']))
    placed=c.place_media(str(media/'dev_video.mp4'),25,source_in=1,source_out=4,media='both',video_track=0,audio_track=0,sequence='Smoke_Main')
    record('trimmed-source placement',all(abs(x['inPoint']-1)<1e-6 and abs(x['outPoint']-4)<1e-6 for x in placed['created']))
    c.add_transition(incoming=True,duration_tc='00:00:00:06',sequence='Smoke_Main')
    copied=c.clone_or_move(0,0,1,sequence='Smoke_Main');record('video edge transition copy',copied['transitions']>=1)
    c.add_audio_transition('Constant Power',duration_tc='00:00:00:06',sequence='Smoke_Main',incoming=True)
    copied=c.clone_av(0,0,2,1,sequence='Smoke_Main');record('audio edge transition copy',copied['audio']['transitions']>=1)
    c.animate(0,0,[{'component':'AE.ADBE Opacity','index':0,'keys':[{'seconds':0,'value':0},{'seconds':1,'value':100}]}],sequence='Smoke_Main',time_space='clip')
    opacity=next(x for x in c.inspect_native(0,0,sequence='Smoke_Main') if x['matchName']=='AE.ADBE Opacity')
    record('clip-relative keys include source in point',all(1-1e-6<=k['seconds']<=4+1e-6 for k in opacity['properties'][0]['keys']))
    if a.visual:
        from PIL import Image
        from pr_controller.visual import photo_card
        items=[]
        for index,color in enumerate(['#a45040','#34789a']):
            path=workspace/f'photo_{index}.png';Image.new('RGB',(300,400),color).save(path);items.append(photo_card(path,workspace/f'card_{index}.png'))
        bg=workspace/'background.png';Image.new('RGB',(1920,1080),'#e9e5df').save(bg);background=dict(item=str(bg),width=1920,height=1080)
        c.create_composition('Smoke_Wall',background,6);c.build_photo_wall(items,6,sequence='Smoke_Wall',columns=2)
        record('photo wall recipe',len(c.timeline('Smoke_Wall')['video'][1]['clips'])==1)
        c.create_composition('Smoke_Fan',background,5);c.build_page_fan(items,5,sequence='Smoke_Fan',focus_index=1)
        record('page fan recipe',len(c.timeline('Smoke_Fan')['video'][2]['clips'])==1)
        c.preview(workspace/'fan_preview',4,sequence='Smoke_Fan')
    if a.preset:
        result=c.export_direct(workspace/'native_export.mp4',a.preset,sequence='Smoke_Main');record('direct sequence export',result['exists'] and result['bytes']>0)
    c.save_project();print(json.dumps({'passed':len(results),'project':str(project)},indent=2))

if __name__=='__main__':main()
