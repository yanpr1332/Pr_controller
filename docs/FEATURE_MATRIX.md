# Completed implementation map

| Review item | Implementation |
| --- | --- |
| Early batch return and multiline parsing | Per-job IDs, atomic final replies, explicit completion, structured JSON |
| Duplicate worker execution | Claim by rename before mutation, engine generation guard |
| Timeout cleanup / lost scripts | Jobs retained, status lookup and queued cancellation |
| Forced PR termination | Explicit installation/connection; restart flag rejected |
| Wrong active sequence / wrong QE item | sequenceID resolution and activation, gap-aware QE clip iteration |
| Ambiguous names / shared relinking | Iterative catalog, ID/path selectors, material-level affected-instance preview |
| Seconds, ticks and frame clocks | time/ticks/frame_ticks, explicit keyframe time spaces |
| Slow keyframe writes | Batch writes without repeated UI refresh, sampled smooth easing |
| Cross-track ripple and partial recovery | Overwrite into validated free spans, strict effect/property validation, transactions |
| Linked AV and group moves | Paired cloning/linking, source identity validation, delete after successful restoration |
| Source bounds and stream selection | Explicit range mapping and isolated partner tracks |
| Timeline changes and markers | Dry-run/application shifts with locked-track and collision checks |
| Sequence and image settings | configure_sequence, contain/cover fit, pixel-aspect input |
| Export and previews | Direct whole-sequence export, retained AME adapter, native timecode PNG preview |
| Repeated photo/PDF scripts | Wall/fan composition APIs, optional full-image shadow cards and PDF rendering |
| Subtitle formats and offsets | SRT/VTT/MD, source registration, native import and source-based export |
| Media movement | Catalog/offline flags, deterministic collision-safe collection manifest, optional probing |
| Repository organization | Installable package, CLI/shim, CI, examples, fixtures generator and tests |

## Explicit host boundaries

Some third-party properties cannot be read or written through the installed API. Copies fail with the source retained; transactional callers can restore the entire pre-edit project. Unsupported transition alignment similarly fails instead of claiming success.

Caption正文回读在当前 ExtendScript API 中存在限制，已提供注册字幕源文件的替代路径。原生版本若没有正文 getter，会明确拒绝回读。运行中的原生同步导出不能由同一个阻塞脚本安全取消，排队任务可以取消。Media collection copies referenced files and a manifest; fonts, plugins and unexposed MOGRT dependencies remain installation dependencies.

These are exposed host limitations with defined alternatives, not silent success paths. Every Premiere upgrade needs a new native regression run; the automated CI does not substitute for that.
