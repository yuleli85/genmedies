import { useState } from 'react'
import toast from 'react-hot-toast'
import { generateVideos, pollVideoTask, poll, BASE_URL } from '../api'

export default function StepVideos({ scenesData, imagesData, project, portrait, initialVideosData, onDone }) {
  const initialVideos = initialVideosData?.videos || []
  const [phase, setPhase] = useState(initialVideos.length > 0 ? 'partial' : 'idle')
  const [useKling, setUseKling] = useState(false)
  const [testMode, setTestMode] = useState(false)
  const [videos, setVideos] = useState(initialVideos)
  const [message, setMessage] = useState('')
  const [currentIdx, setCurrentIdx] = useState(0)

  const allScenes = (scenesData?.scenes || []).map((scene) => {
    const img = (imagesData || []).find((i) => i.scene_id === scene.scene_id)
    return { ...scene, image_path: img?.image_path || '', image_url: img?.image_url || '' }
  })
  const scenesWithImages = testMode ? allScenes.slice(0, 2) : allScenes

  // 计算还没生成成功的分镜
  const doneIds = new Set(videos.map((v) => v.scene_id))
  const pendingScenes = scenesWithImages.filter((s) => !doneIds.has(s.scene_id))

  const startGenVideos = async (existingVideos = [], force = false) => {
    setPhase('generating')
    setCurrentIdx(existingVideos.length)
    setMessage(force ? '强制重新生成所有视频（跳过缓存）...' : '开始生成分镜视频...')
    // 只把未完成的场景发给后端，但告知总数用于显示正确进度
    const scenesToGenerate = scenesWithImages.filter(
      (s) => !existingVideos.find((e) => e.scene_id === s.scene_id)
    )
    try {
      const { data: { task_id } } = await generateVideos(
        project, scenesToGenerate, useKling, existingVideos, scenesWithImages.length,
        portrait?.path || '', force
      )

      const result = await poll(async () => {
        const { data } = await pollVideoTask(task_id)
        if (data.status === 'running') {
          const match = data.message.match(/(\d+)\/(\d+)/)
          if (match) setCurrentIdx(parseInt(match[1]))
          setMessage(data.message)
          // 实时更新已完成的视频
          if (data.result?.videos?.length) {
            setVideos(data.result.videos)
          }
        }
        return { data }
      }, 5000, 600000)

      const allVideos = result.result.videos
      setVideos(allVideos)
      setPhase('done')
      onDone(result.result)
      const cached = allVideos.filter((v) => v.from_cache).length
      const msg = cached > 0 ? `（${cached} 个命中缓存，${allVideos.length - cached} 个新生成）` : ''
      toast.success(`${allVideos.length} 个视频生成完毕 ${msg}`)
    } catch (e) {
      // 优先用后端返回的部分结果，其次用轮询期间实时更新的
      const partialVideos = e.partialResult?.videos?.length
        ? e.partialResult.videos
        : videos.filter((v) => v.video_path)
      setVideos(partialVideos)
      setPhase(partialVideos.length > 0 ? 'partial' : 'idle')
      toast.error(`生成中断: ${e.message}${partialVideos.length > 0 ? `（已完成 ${partialVideos.length} 个）` : ''}`)
    }
  }

  const total = scenesWithImages.length

  return (
    <div className="step-panel">
      <h2>第四步：生成分镜视频</h2>
      <p className="step-desc">为每个镜头生成短视频，文件名包含时间戳。</p>

      {(phase === 'idle' || phase === 'partial') && (
        <>
          {phase === 'partial' && (
            <div className="partial-notice">
              <p>已完成 <strong>{videos.length}</strong> / {total} 个镜头，还剩 <strong>{pendingScenes.length}</strong> 个未生成。</p>
              <p className="partial-hint">点击"继续生成"将跳过已完成的镜头，节省费用。</p>
            </div>
          )}

          <div className="option-row">
            <label className="toggle-label">
              <input type="checkbox" checked={useKling} onChange={(e) => setUseKling(e.target.checked)} />
              使用 Kling AI 图生视频（取消则用 FFmpeg 静态图降级）
            </label>
          </div>
          <div className="option-row">
            <label className="toggle-label toggle-test">
              <input type="checkbox" checked={testMode} onChange={(e) => setTestMode(e.target.checked)} />
              测试模式：只生成前 2 个镜头，快速验证流程
            </label>
          </div>

          <div className="scenes-preview">
            {scenesWithImages.map((scene) => {
              const done = doneIds.has(scene.scene_id)
              return (
                <div key={scene.scene_id} className={`scene-mini ${done ? 'scene-mini-done' : ''}`}>
                  {scene.image_url && (
                    <img src={`${BASE_URL}${scene.image_url}`} alt={`scene ${scene.scene_id}`} />
                  )}
                  <span>
                    {done ? '✓ ' : ''}镜头 {scene.scene_id} · {scene.duration}s
                  </span>
                </div>
              )
            })}
            {testMode && allScenes.length > 2 && (
              <div className="scene-mini scene-mini-hidden">
                <span className="scene-mini-more">+{allScenes.length - 2} 个已跳过</span>
              </div>
            )}
          </div>

          {phase === 'partial' ? (
            <div className="action-row">
              <button className="btn-secondary" onClick={() => { setVideos([]); setPhase('idle') }}>重新全部生成</button>
              <button className="btn-primary large" onClick={() => startGenVideos(videos)}>
                继续生成（剩余 {pendingScenes.length} 个）
              </button>
            </div>
          ) : (
            <button className="btn-primary large" onClick={() => startGenVideos([])}>
              开始生成视频 ({total} 个镜头{testMode ? '，测试模式' : ''})
            </button>
          )}
        </>
      )}

      {phase === 'generating' && (
        <div className="progress-block">
          <div className="spinner" />
          <p>{message}</p>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${total ? (currentIdx / total) * 100 : 0}%` }} />
          </div>
          <p className="progress-text">{currentIdx} / {total}</p>
        </div>
      )}

      {phase === 'done' && (
        <div className="videos-list">
          <h3>生成的分镜视频</h3>
          {videos.map((v) => (
            <div key={v.scene_id} className="video-item">
              <video src={`${BASE_URL}${v.video_url}`} controls width={320} height={180} />
              <div>
                <p>镜头 {v.scene_id} · {v.duration}s{v.from_cache ? ' · 缓存' : ''}</p>
                <a href={`${BASE_URL}${v.video_url}`} download>下载</a>
              </div>
            </div>
          ))}
          <div className="action-row">
            <button className="btn-secondary" onClick={() => { setVideos([]); startGenVideos([], true) }}>
              强制重新生成（忽略缓存）
            </button>
            <button className="btn-primary" onClick={() => onDone({ videos })}>进入合成步骤</button>
          </div>
        </div>
      )}
    </div>
  )
}
