"""Generate testsrc2 + silent stereo fixtures; requires FFmpeg, not Premiere."""
import argparse,subprocess
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--wsl',action='store_true');p.add_argument('--ffmpeg',default='ffmpeg');a=p.parse_args();root=Path(a.directory).resolve();root.mkdir(parents=True,exist_ok=True)
    def output(name):
        target=root/name
        if target.exists():raise FileExistsError(target)
        return '/mnt/'+target.drive[0].lower()+target.as_posix()[2:] if a.wsl else str(target)
    prefix=['wsl.exe','-d','Debian','--','/usr/bin/ffmpeg'] if a.wsl else [a.ffmpeg]
    subprocess.run(prefix+['-v','error','-f','lavfi','-i','testsrc2=size=1280x720:rate=30','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','5','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',output('dev_video.mp4')],check=True)
    subprocess.run(prefix+['-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','3','-c:a','pcm_s16le',output('dev_audio.wav')],check=True)
if __name__=='__main__':main()
