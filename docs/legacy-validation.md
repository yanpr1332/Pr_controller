# Premiere Pro 2026 Automation

正式控制器：

`D:\computer\Adobe\Premiere Pro\premiere_controller.py`

Premiere 版本：26.0.1。

Startup Runner：

`D:\computer\Adobe\Premiere Pro\scripts\controller_runner.jsx`

安装到：

`Adobe Premiere Pro 2026\Scripts\Startup\99_chatgpt_controller_runner.jsx`

## 控制架构

当前 Startup Runner 使用 `app.setTimeout()` 维持常驻轮询。\n\n早期版本使用 `app.encoder.setTimeout()`，已确认会被 AME 批处理干扰；现已迁移到独立的 `app.setTimeout()`。Python 端同时增加了长操作后的 5 秒 heartbeat 恢复窗口。

因此 Premiere 已经打开时，Python 可以直接向 `_runtime\task.jsxinc` 投递任务并立即执行，
不需要为了每一个命令重启 Premiere。

已实测：

`premiere_controller.py status`

可在 Premiere 保持运行时直接返回当前 project / sequence。

## 已验证稳定能力

- 新建 / 打开 / 保存工程
- Bin / 素材导入
- 从 clips 创建 sequence
- Marker
- Motion / Crop
- Opacity / keyframes
- Video Effect
- Transition
- SRT -> Caption Track
- MOGRT 插入
- MOGRT Source Text
- MOGRT Text Position / Scale / Rotation / Opacity
- MOGRT 动态定位 `find_mogrt_clips()`
- Auto Reframe
- Track Mute / Lock
- Audio Volume
- Audio Volume keyframes
- Speed
- Reverse
- Scene Edit Detection
- Lumetri Basic parameters
- Frame Export PNG
- Proxy attach
- Link / Unlink selection
- Razor cut on video track
- Remove video clip
- Frame Blend toggle
- Time Interpolation type
- Insert project item at timeline time
- Overwrite project item at timeline time
- Scale to Frame Size
- Slip edit by frame offset
- Slide edit by frame offset
- Trim clip start/end by timeline seconds
- Move clip on the same track while preserving duration
- Programmatic ripple trim end (same video track)
- Programmatic ripple delete (same video track)
- Move linked video/audio together
- Trim linked video/audio end together
- Trim linked video/audio start together
- Ripple delete linked video/audio together
- Audio track Insert / Overwrite
- Ripple trim linked video/audio end together
- Cross-track video move via insert + state restore + source removal

## 关键验证结果

### Persistent bridge

Premiere 保持运行时可连续执行 Python -> JSX 任务，无需重启。

### Speed / Reverse

实测：

- 1x -> 0.5x：5s -> 10s
- 0.5x -> 1x：10s -> 5s
- Reverse false -> true
- Reverse true -> false

均返回 `ok=true`。

### Scene Edit Detection

测试素材 1 clip 被自动识别并切成 2 clips。

### Lumetri

已验证参数级写入：

- Temperature
- Tint
- Saturation
- Exposure
- Contrast
- Highlights
- Shadows
- Whites
- Blacks

实测 Exposure / Contrast / Saturation 写入并读回成功。

### MOGRT

已验证：

- Source Text
- Position
- Scale
- Rotation
- Opacity

测试值写入后均可读回。

注意：sequence index 会随工程新增 sequence 漂移，因此新增
`find_mogrt_clips()` 动态定位 MOGRT。

### Frame Export

QE `exportFramePNG()` 已实测，PNG 文件真实生成。

### Proxy

`ProjectItem.attachProxy()` 已实测：

- return true
- hasProxy true
- getProxyPath() 返回正确 proxy 文件路径

### Link / Unlink

实测选中一组 video/audio clip 后：

- linkSelection() -> linked items = 2
- unlinkSelection() -> linked items = 0

### Audio

Clip Volume Level 可直接设置并可关键帧化。

Premiere 内部 clip Volume 的数值不是 dB；controller 已提供 dB -> 内部 scale 转换。

## 扩展能力与已知边界

### Timeline edit ops

Newly verified on `Controller Edit Ops Test 20261006`:

- `razor_video_track()`: 1 clip -> 2 clips, then 2 -> 3 clips
- `remove_video_clip()`: 3 clips -> 2 clips
- `set_video_frame_blend(True)`: returned true
- `set_video_time_interpolation(1)`: returned true

`QEItem.rippleDelete()` still returns false in the current Premiere 26.0.1 environment, so it is not exposed as a stable controller method.

### Timeline core ops 2

Newly verified:

- `insert_project_item()`: Track.insertClip() returned true and clip count increased.
- `overwrite_project_item()`: Track.overwriteClip() returned true.
- `scale_video_to_frame_size()`: ProjectItem.setScaleToFrameSize() returned true.
- `slip_video_clip(offset_frames)`: QE slip accepts a frame-offset string; 5 frames changed source in/out by 0.2 s in the 25 fps test sequence.
- `slide_video_clip(offset_frames)`: QE slide accepts a frame-offset string; 5 frames moved the edit by 0.2 s in the 25 fps test sequence.

Standard TrackItem also exposes a `move()` method, but its argument contract is not yet verified, so it is not exposed in the controller yet.

### DOM trim / move

Newly verified using standard TrackItem properties:

- `trim_video_clip_start()`: writable `TrackItem.start`; test moved start 7 -> 8 s.
- `trim_video_clip_end()`: writable `TrackItem.end`; test moved end 4 -> 3.5 s.
- `move_video_clip()`: sets start/end together and preserves duration; test moved 8-12 -> 9-13 s.
- `ripple_trim_video_clip_end()`: controller-level same-track ripple trim. Test changed first clip 0-5 -> 0-4 s and shifted the following clip 5-10 -> 4-9 s.

QE `moveToTrack()` and `setStartPosition()/setEndPosition()` still reject the tested public argument forms with `Illegal Parameter type`, so cross-track move and native QE trim are not exposed yet.

### Ripple delete / linked A-V

Newly verified:

- `ripple_delete_video_clip_dom()`: controller-level ripple delete. In a 3-clip 0-5 / 5-10 / 10-15 test, deleting the middle clip produced 0-5 / 5-10 with no gap.
- `move_linked_av(delta_seconds)`: linked video and audio moved together; test changed both 0-5 -> 1-6 s.
- `trim_linked_av_end(seconds)`: linked video and audio end points changed together; test changed both ends 6 -> 5 s.

These linked A/V helpers use the standard `getLinkedItems()` relationship and writable TrackItem start/end properties rather than UI automation.

### Linked A-V advanced edit

Newly verified:

- `trim_linked_av_start(seconds)`: linked video and audio start points changed together; test changed both 1 -> 2 s.
- `ripple_delete_linked_av()`: linked video/audio pair deleted together, and later video/audio clips shifted forward by the deleted duration. In the two-pair test, deleting pair 0-5 shifted pair 5-10 to 0-5 while preserving the link relationship.

QE `razor()` on linked video/audio returned true on both tracks in one test but did not change standard DOM clip counts, so linked razor is not yet marked stable.

### Audio insert / linked ripple trim / cross-track move

Newly verified:

- `insert_audio_project_item()` and `overwrite_audio_project_item()`: audio Track insert/overwrite both returned true and landed at the requested timeline positions.
- `ripple_trim_linked_av_end()`: linked V/A pair trimmed together and all later V/A clips shifted by the trim delta. Test changed pair 0-5 -> 0-4 and shifted pair 5-10 -> 4-9, preserving links.
- `move_video_clip_to_track()`: reliable replacement for QE moveToTrack(). It inserts the same ProjectItem on the destination video track, restores start/end/inPoint/outPoint, then removes the source clip. Test preserved start=0, end=5, in=1, out=4 while moving V0 -> V2.

The QE native `moveToTrack()` remains unexposed because its argument contract still rejects tested public forms.

### Cross-track state preservation

`move_video_clip_to_track()` was upgraded to snapshot and restore matching clip components and keyframes before removing the source clip.

Verified:

- Motion Scale 73 remained 73 after V0 -> V1 move.
- Opacity keyframes at 1 s = 20 and 3 s = 80 were restored on the destination clip.
- Timeline start/end and source inPoint/outPoint remain preserved as before.

The method now also recreates missing non-base video effects by the source component's localized display name, then restores their properties and keyframes. Verified with Crop (`AE.ADBE AECrop`): the destination clip rebuilt the effect, preserved Right=7, and restored Left keyframes at 1 s = 5 and 3 s = 25. A time-varying property may still report its default static `getValue()` while its keyframed values remain correct; verify animated properties through `getKeys()/getValueAtKey()`. Complex effects with unusual property types, nested controls, or non-scalar/color data still need per-effect validation.

### Full effect-aware cross-track clone

`move_video_clip_to_track()` now performs an effect-aware clone before deleting the source clip:

1. Snapshot timeline timing, source in/out points, component match/display names, static values, and keyframes.
2. Insert the same ProjectItem on the destination video track.
3. Recreate missing non-base effects through QE using the source component's localized display name.
4. Restore matching component properties and keyframes.
5. Remove the source clip only after the destination state has been rebuilt.

Verified with Crop: `rebuiltEffects=1`, Right=7 preserved, and keyframes 1:5 / 3:25 preserved after moving V0 -> V1.

### Linked A-V cross-track move

New stable method: `move_linked_av_to_tracks(target_video_track_index, target_audio_track_index, ...)`.

Verified on a linked V/A pair:

- Video moved V0 -> V1 and audio moved A0 -> A1.
- Source V0/A0 became empty; destination V1/A1 each contain one clip.
- Video Crop effect was rebuilt on the destination.
- Crop Right=7 preserved.
- Crop keyframes 1 s = 5 and 3 s = 25 preserved.
- Video and audio start/end and in/out points preserved.
- Audio base component state (Internal Volume Stereo / Internal Channel Volume Stereo) was snapshotted and restored.
- Final link relationship preserved: video linked count=2, audio linked count=2.

The method uses feature matching for the linked audio item rather than ExtendScript object identity, because linked TrackItem objects do not reliably compare equal with the objects returned from AudioTrack.clips.

### Multi-effect order preservation

QE inserts newly added video effects ahead of previously added custom effects. Therefore effect-aware clone rebuilds missing effects in reverse source order.

Verified with source component order:

`Opacity -> Motion -> Lumetri -> Crop`

After cross-track move, the destination component order remained exactly:

`Opacity -> Motion -> Lumetri -> Crop`

A forward rebuild had previously produced the wrong custom-effect order (`Crop -> Lumetri`); this is now fixed in both single-video and linked V/A cross-track move paths.

### Audio Effects

已解决。之前失败的根因是：QE 必须处于正确的 active sequence，同时中文 Premiere 应使用本地化效果名并匹配 channelType。

已通过 qe.project.getAudioEffectList() 枚举本机音频效果，包括“参数均衡器”“动态”“强制限幅”等。

正式接口：
- list_audio_effect_names(effect_type=0)
- add_audio_effect(name, ..., channel_type=0)

实测“参数均衡器”：
- addAudioEffect() -> true
- 标准 DOM components：2 -> 3
- 新增组件 matchName：8edcd326-33de-4a4d-985b-f1bf48ed1427
- 参数数：46

Linked A/V clone/move 也已支持重建缺失的音频 Effect，再恢复其参数和关键帧。端到端测试同时复制 Crop + 参数均衡器时：
- rebuiltEffects=1
- rebuiltAudioEffects=1
- video properties restored=20
- audio properties restored=81
- link relationship remains 2/2\n\n### MOGRT Font / Fill Color

仍是当前主要 API 边界。

Basic Title MOGRT 已确认：
- TrackItem.getMGTComponent() -> null
- AE.ADBE Text 暴露 22 个普通 properties
- Source Text / Position / Scale / Rotation / Opacity 均可写
- 所有 Property 虽反射出 getColorValue()/setColorValue()，但逐项调用均返回 Unknown error
- Source Text 的 getValue() 只返回纯字符串，不包含字体/填充样式对象

因此 Font / Fill Color 没有稳定的 DOM/QE 写入入口。当前不提供伪造 setter；后续若继续，只建议研究 UI 自动化或 Adobe 后续开放的 text-style API。\n\n### Media Encoder

已解决并完成真实文件验证。

环境：
- Premiere Pro：26.0.1.3
- Adobe Media Encoder：26.0.0.60

使用真实系统 preset：
MediaIO/systempresets/3F3F3F3F_4D6F6F56/H264 Match Source - High bitrate.epr

正式接口：
- encode_sequence_ame(output_path, preset_path, ...)

验证结果：
- launchEncoder() 成功
- encodeSequence() 返回有效 job ID
- startBatch() -> true
- 实际输出文件生成成功（测试文件约 2.9–4.5 MB）
- 请求路径写 .mp4 时，该 preset 实际输出 .mov；最终扩展名由 preset/exporter 决定
- AME 完成后紧接 status() 仍正常，bridge 不再断线

### Duplicate / batch / split

新增并验证：
- clone_video_clip_to_track()：Effect-aware Duplicate，不删除源 clip；Crop 重建、参数和 keyframes 均保留。
- move_video_clips_to_track()：按降序 clip index 批量跨轨移动，3/3 实测成功。
- split_linked_av_at()：Linked V/A 的语义切割替代不可靠 QE Razor。1x clip 在 2.5s 切割后，左右 V/A 的 timeline 与 source in/out 均正确为 0–2.5 / 2.5–5，并成功 relink 右半段。
- clone_linked_av_to_tracks()：整组 linked V/A Duplicate。
- move_linked_av_pairs_to_tracks()：批量 linked V/A 跨轨移动。

### Transition preservation

新增：
- list_video_transitions()
- copy_clip_edge_transitions()

Cross Dissolve 实测：
- source duration = 12 frames
- 名称 / frame range / alignment 可枚举
- 复制到目标 clip edge 成功

Transition 是轨道边界对象而不是 clip component。单独搬走一个 clip 后若目标轨缺少原邻居，Premiere 会将原居中 transition（alignment=0.5）转换成单边 edge transition（测试为 alignment=1.0）；这是时间线语义变化。

### Complex state clone

复杂状态回归已通过：
- Motion Position [0.3, 0.4] -> [0.3, 0.4]
- Motion Scale 88 -> 88
- Lumetri Saturation 82 -> 82
- Lumetri Exposure 1.25 -> 1.25
- Lumetri 组件在目标轨自动重建
- 多 Effect 顺序保持：Opacity -> Motion -> Lumetri -> Crop\n\n## 安全原则

- 正式 controller 不自动删除用户工程或素材。
- persistent bridge 正常时不重启 Premiere。
- 只有显式 `restart=True` 才允许强制 reload bridge。
- 高风险实验只在 PR_Dev_Test.prproj 中进行。


## 2026-10-07 全量验收

本轮对近期新增能力进行了串行回归验收，所有高风险操作均限定在 PR_Dev_Test.prproj。

### 通过项

- Audio Effect：参数均衡器添加成功，audio components 2 -> 3。
- Effect-aware Duplicate：源 clip 保留，目标 clip 重建 Crop，Right=9 与 keyframe 1s=6 保留。
- Linked A/V Split：2.5s 切割后 V/A 均为 0-2.5 / 2.5-5，左右两组均 linked=2。
- Batch video cross-track move：3 clips 最终准确保持 0-5 / 5-10 / 10-15。
- Linked A/V clone：源 V/A 与目标 V/A 同时存在，源/目标均 linked=2。
- Linked A/V batch move：两组最终准确保持 0-5 / 5-10，V/A 各自 linked=2。
- Transition copy：Cross Dissolve 12 frames 成功复制。
- Complex clone：Motion Position [0.3,0.4]、Scale 88、Crop Right 11、Crop keyframe 2s=17、Lumetri Saturation 82 / Exposure 1.25 均保留。
- Effect stack order：Opacity -> Motion -> Lumetri -> Crop 保持不变。
- Linked clone with audio effect：Crop 与“参数均衡器”同时在目标 V/A 上重建，rebuiltEffects=1，rebuiltAudioEffects=1。
- AME：真实输出文件生成；导出后 persistent bridge status() 仍正常。

### Batch move 修复

回归测试发现旧版 batch move 在同一目标轨连续调用 insertClip() 时会受 ripple 影响，导致部分目标 clip 时间位置重复。

已改为两阶段策略：

1. 按升序 clip index 先完成所有 effect-aware clone；
2. 全部目标 clip 创建成功后，再按降序删除源 clip。

Linked V/A batch move 同样采用此策略，并新增 remove_linked_av() 作为非 ripple 的成对删除原语。

修复后验收：

- video batch：0-5 / 5-10 / 10-15
- linked V/A batch：0-5 / 5-10
- 源轨清空，目标轨数量正确，linked relationship 保留

### 当前主要边界

MOGRT Font / Fill Color 仍无稳定 DOM/QE setter。2026-10-07 复核 Basic Title：

- getMGTComponent() -> null
- AE.ADBE Text 共 22 个普通 properties
- Source Text 仍返回纯字符串
- 22/22 property 调用 getColorValue() 均为 Unknown error
- TrackItem 反射出的相关方法只有 getMGTComponent / isMGT

因此继续保留为明确 API 边界，不提供伪造 setter。


## 2026-10-07 第二阶段高级编辑能力

### 通用 Component / Effect API

新增：

- list_video_effect_names()：QE 枚举本机视频效果，当前环境共 143 个。
- inspect_clip_components()：稳定枚举任意 video/audio clip 的 components、properties、值与可选 keyframes。
- set_clip_component_property()：按 component matchName/displayName + property index 写入任意参数。
- set_clip_component_keyframes()：通用关键帧写入，可选择清空已有 keyframes。

验证类型：

- array：Motion Position [0.5,0.5] -> [0.25,0.35]
- number：Motion Scale 100 -> 91
- boolean：Crop boolean false -> true
- keyframes：Crop property 0 写入 1s=8 / 3s=22
- audio number：Internal Volume Stereo 0.1778 -> 0.3
- audio keyframes：1s=0.2 / 3s=0.4

最初基于大 JSON 的 inspect 实现会让 persistent bridge 停止响应，已废弃并改成轻量 URI-encoded 文本协议；新实现回归稳定。

当前安装环境没有扫描到 Sapphire / Boris / Universe / Red Giant / Twixtor / Neat / Topaz 等明显第三方视频插件，因此第三方插件暂未做品牌级端到端测试；通用 API 已具备相同参数枚举/写入路径。

### Video group transitions

新增：

- copy_video_group_transitions()
- clone_video_group_to_track()
- move_video_group_to_track()

两段相邻 video clips 连同 Cross Dissolve 一起 Clone/Move 后：

- clip positions：0-5 / 5-10
- transition duration：12 frames
- transition alignment：0.5

因此成组迁移时可以保留真正的居中转场，而不是单 clip edge copy 的单边退化。

### Audio transitions

新增：

- list_audio_transition_names()
- add_audio_transition()
- list_audio_transitions()
- copy_audio_group_transitions()

QE audio track 的 numTransitions 会包含两个没有 name 的头尾哨兵，正式实现会主动过滤，只返回真实 transition。

验证：

- addTransition() -> true
- real transition count：0 -> 1
- source：125-137 frames，12 frames
- group copy 到 A1：同名、125-137、12 frames

音频 transition 不像视频 Cross Dissolve 一样围绕切点中心分布；边界识别使用 transition start 对 outgoing edge / transition end 对 incoming edge，同时保留 center fallback。

### Full linked A/V timeline block

新增：

- get_linked_audio_locations()
- clone_linked_av_group_to_tracks()
- move_linked_av_group_to_tracks()

端到端验收：

源 V0/A0：

- 2 组 linked V/A：0-5 / 5-10
- 第一组 video 带 Crop
- 第一组 audio 带参数均衡器
- 两个 video clips 中间有 12-frame Cross Dissolve
- 两个 audio clips 中间有 12-frame audio transition

Clone 到 V1/A1，再 Move 源块到 V2/A2 后：

- V0/A0：0 clips
- V1/A1：2 + 2 clips
- V2/A2：2 + 2 clips
- 所有目标 V/A pairs：linked count = 2
- V1/V2 第一 clip components = 3（Crop 保留）
- A1/A2 第一 clip components = 3（参数均衡器保留）
- V1/V2 transition：Cross Dissolve 119-131
- A1/A2 transition：125-137
- clip timeline positions 均保持 0-5 / 5-10

这代表 controller 已可搬运完整可编辑时间线结构，而不只是单个 clip。

### Editor-level sequence / track / media APIs

新增：

- set_sequence_in_out()
- clone_sequence()
- create_subsequence()
- set_clip_disabled()
- set_clip_color_label()
- relink_clip_media()
- add_tracks()
- remove_empty_tracks()
- remove_video_track()
- remove_audio_track()

验证：

- Sequence In/Out：1-4s
- Sequence clone：count +1，clone 后 active sequence 为真实副本
- createSubsequence：1-4s 生成 3s 子序列
- clip disabled：false -> true -> false
- ProjectItem color label：0/5 -> 6
- remove empty tracks：3/3 -> 1/1
- addTracks：1/1 -> 2/2
- remove V/A track：2/2 -> 1/1
- changeMediaPath：relink_src.mp4 -> relink_dst.mp4 -> relink_src.mp4

注意：set_clip_color_label() 实际作用于 clip 的 ProjectItem，因此会影响同一素材的其它实例，不是 timeline-instance-only label。

### Freeze frame

新增 create_freeze_frame_clip()，组合已有稳定能力：

1. QE exportFramePNG()
2. import PNG
3. insert still image
4. 写入 timeline start/end

实测：

- source frame：00:00:02:00
- target：V1
- timeline：5-7s
- PNG 实际生成且 project item / timeline clip 均存在

### Work Area 边界

Sequence 标准 setWorkAreaInPoint()/setWorkAreaOutPoint() 与 QE setWorkInOutPoints() 在 PR 26.0.1 中都不能稳定改变读回值。

QE timecode 形式虽然返回 true，但 workInPoint.secs/workOutPoint.secs 仍为 0-0。

因此 Work Area 目前不作为正式稳定能力；Sequence In/Out 已稳定可用。
