"""拉片用镜头切点关键帧提取。

用法:
  python extract_shots.py <video> [--out DIR] [--th 0.25] [--gap 0.4] [--weak-th 0.15]

输出 (--out 默认 shots/):
  shot_NNN_IN_MMmSSs.jpg   每个镜头的入点帧(切点帧)
  shot_NNN_OUT_MMmSSs.jpg  每个镜头的出点帧(切点前一帧)
  index.csv                镜头表
"""
import argparse, csv, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

FFMPEG = r"ffmpeg-win-x86_64-v7.1.exe"


def tcode(t):
    return f"{int(t // 60):02d}m{int(t % 60):02d}s"


def probe_duration(video):
    out = subprocess.run([FFMPEG, '-hide_banner', '-i', video],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True, encoding='utf-8', errors='ignore').stderr
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def scene_scores(video, workdir):
    """全片 scene score: 返回 [(pts_time, score)]"""
    f = os.path.join(workdir, 'scene_scores.txt')
    if not os.path.exists(f):
        subprocess.run([FFMPEG, '-y', '-hide_banner', '-i', video,
                        '-vf', "select=gt(scene\\,0.001),metadata=print:file=" + f.replace('\\', '/'),
                        '-an', '-f', 'null', '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    txt = open(f, encoding='utf-8', errors='ignore').read().replace('\r', '\n')
    ts = [float(x) for x in re.findall(r'pts_time:([\d.]+)', txt)]
    sc = [float(x) for x in re.findall(r'scene_score=([\d.]+)', txt)]
    return sorted(zip(ts, sc))


def export_candidates(video, workdir, weak_th):
    """导出所有 score>weak_th 的帧, 返回 [(n, pts_time, filepath)]"""
    log = os.path.join(workdir, 'cand_log.txt')
    has_cache = os.path.exists(log) and any(f.startswith('cand_') for f in os.listdir(workdir))
    if not has_cache:
        subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'info', '-i', video,
                        '-vf', f"select=gt(scene\\,{weak_th}),showinfo", '-vsync', '0', '-q:v', '3',
                        os.path.join(workdir, 'cand_%05d.jpg')],
                       stderr=open(log, 'w', encoding='utf-8'))
    txt = open(log, encoding='utf-8', errors='ignore').read()
    out = []
    for seg in txt.split('[Parsed_showinfo')[1:]:
        mn = re.search(r'\bn:\s*(\d+)', seg)
        mt = re.search(r'pts_time:\s*([\d.]+)', seg)
        if mn and mt:
            n = int(mn.group(1))
            out.append((n, float(mt.group(1)), os.path.join(workdir, f"cand_{n+1:05d}.jpg")))
    return sorted(out)


def pick_cuts(cands, scores, th, gap):
    """贪心: 按分数降序取局部峰值, 时间间距 > gap"""
    lut = {round(t, 3): s for t, s in scores}
    def score_of(t):
        if round(t, 3) in lut:
            return lut[round(t, 3)]
        near = [s for tt, s in scores if abs(tt - t) < 0.02]
        return max(near) if near else 0.0

    items = [(score_of(t), t, p) for (n, t, p) in cands]
    cuts = []
    for s, t, p in sorted(items, key=lambda x: -x[0]):
        if all(abs(t - c[1]) > gap for c in cuts):
            cuts.append((s, t, p))
    return sorted(cuts, key=lambda x: x[1])


def grab_frame(video, t, dst):
    subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-ss', f'{t:.3f}',
                    '-i', video, '-frames:v', '1', '-q:v', '3', dst],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return dst if os.path.exists(dst) else None


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--out', default='shots')
    ap.add_argument('--th', type=float, default=0.25, help='硬切阈值')
    ap.add_argument('--gap', type=float, default=0.4, help='相邻切点最小间隔(秒)')
    ap.add_argument('--weak-th', type=float, default=0.15, help='候选帧阈值/疑似切点阈值')
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    dur = probe_duration(a.video)
    print(f'时长 {dur:.2f}s  计算镜头变化分数...')
    scores = scene_scores(a.video, a.out)
    print('  导出候选切点帧...')
    cands = export_candidates(a.video, a.out, a.weak_th)
    cuts = pick_cuts(cands, scores, a.th, a.gap)
    print(f'  候选 {len(cands)} 帧 -> 切点 {len(cuts)} 个')

    # 镜头表
    shots = []
    for i, (s, t, p) in enumerate(cuts, 1):
        shots.append({'idx': i, 'in': t, 'score': round(s, 3),
                      'conf': '硬切' if s >= a.th else '疑似/渐变', 'src': p})
    for i, sh in enumerate(shots):
        end = shots[i + 1]['in'] if i + 1 < len(shots) else dur
        sh['out_t'] = end
        sh['dur'] = round(end - sh['in'], 2)

    # IN 帧: 直接复用候选图
    for sh in shots:
        dst = os.path.join(a.out, f"shot_{sh['idx']:03d}_IN_{tcode(sh['in'])}.jpg")
        os.replace(sh['src'], dst)
        sh['in_file'] = os.path.basename(dst)

    # OUT 帧: 切点前 0.1s
    jobs = []
    for sh in shots:
        t = sh['out_t'] - 0.1
        if t > sh['in'] + 0.05:
            dst = os.path.join(a.out, f"shot_{sh['idx']:03d}_OUT_{tcode(t)}.jpg")
            jobs.append((t, dst, sh))
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda j: grab_frame(a.video, j[0], j[1]), jobs))
    for t, dst, sh in jobs:
        if os.path.exists(dst):
            sh['out_file'] = os.path.basename(dst)

    # 清理剩余候选图
    for f in os.listdir(a.out):
        if f.startswith('cand_'):
            os.remove(os.path.join(a.out, f))

    with open(os.path.join(a.out, 'index.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['镜号', '入点(秒)', '出点(秒)', '时长(秒)', '切点分数', '判定', '入点帧', '出点帧'])
        for sh in shots:
            w.writerow([sh['idx'], f"{sh['in']:.2f}", f"{sh['out_t']:.2f}", sh['dur'],
                        sh['score'], sh['conf'], sh['in_file'], sh.get('out_file', '')])

    print(f'完成: {len(shots)} 个镜头 -> {a.out}/')
