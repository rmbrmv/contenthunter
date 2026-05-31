import asyncio, os, sys, json, subprocess
sys.path.insert(0, '/home/claude-user/unic-worker')
os.environ.setdefault('DATABASE_URL', 'postgresql://openclaw:openclaw123@localhost:5432/openclaw')
import asyncpg
import worker as W

ORIG = '/tmp/publish_media/pq_7642_1780224512775.mp4'
OUTDIR = '/tmp/wp111_test'
os.makedirs(OUTDIR, exist_ok=True)

async def main():
    pool = await asyncpg.create_pool(W.DB_URL, min_size=1, max_size=3)
    results = []
    for sid in (31, 34):
        scheme = await W.get_scheme(pool, sid)
        assert scheme, f'scheme {sid} not found'
        content = await W.get_content_for_scheme(pool, scheme, 103)  # project Ирбис
        files = {'original': ORIG}
        ov = content['video']
        print(f"\n=== scheme {sid}: content_video_index={scheme['content_video_index']} -> overlay id={ov['id']} {ov['file_path'].split('/')[-1]} chroma={ov.get('chromakey_color')}")
        # download assets (overlay/audio/logo/pattern) like the worker does
        if content['video']:
            p = f'{OUTDIR}/s{sid}_ov.mp4'; W.download_file(content['video']['file_path'], p); files['overlay_video'] = p
        if content['audio']:
            p = f'{OUTDIR}/s{sid}_oa.mp3'; W.download_file(content['audio']['file_path'], p); files['overlay_audio'] = p
        if content['logo']:
            p = f'{OUTDIR}/s{sid}_logo.png'; W.download_file(content['logo']['file_path'], p); files['logo'] = p
        if content['pattern']:
            p = f'{OUTDIR}/s{sid}_pat.png'; W.download_file(content['pattern']['file_path'], p); files['pattern'] = p
        print(f"    assets: {list(files.keys())}")
        ck = content['video'].get('chromakey_color') if content['video'] else None
        proc = f'{OUTDIR}/s{sid}_proc.mp4'
        cmd = W.generate_ffmpeg(scheme, files, ck, proc)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            print(f"    FFMPEG FAIL rc={r.returncode}\n    {r.stderr[-600:]}")
            results.append((sid, False, 'ffmpeg_fail')); continue
        ok, reason = W.validate_output(ORIG, proc, scheme)
        size = os.path.getsize(proc) if os.path.exists(proc) else 0
        print(f"    FFmpeg OK, output={size/1e6:.2f}MB, validate={ok} ({reason})")
        results.append((sid, ok, reason))
    await pool.close()
    print("\n==== SUMMARY ====")
    for sid, ok, reason in results:
        print(f"scheme {sid}: {'PASS' if ok else 'FAIL'} — {reason}")
    return all(ok for _, ok, _ in results)

ok = asyncio.run(main())
sys.exit(0 if ok else 1)
