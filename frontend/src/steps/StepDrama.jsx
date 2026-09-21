import { useState, useEffect, useCallback } from 'react'
import toast from 'react-hot-toast'
import {
  dramaCreateProject, dramaGetProject, dramaUpdateProject,
  dramaGenScript, dramaGenShots, dramaGenKeyframes,
  dramaGenVideos, dramaGenDub, dramaGenLipsync, dramaMerge, dramaClearCache,
  dramaUploadCharacterRef,
  pollDramaTask, poll, BASE_URL,
} from '../api'

// ── ShotGrid: reusable progress grid for kf/vid/dub phases ──
function ShotGrid({ shots, shotStatus, field, label, frames, running, message, stepError, onBack, onRetry, onNext, nextLabel, testRow }) {
  const failedIds = shots.filter(s => shotStatus[s.shot_id]?.[field] === 'error').map(s => s.shot_id)
  const doneCount = shots.filter(s => ['done', 'cached'].includes(shotStatus[s.shot_id]?.[field])).length
  const cachedCount = shots.filter(s => shotStatus[s.shot_id]?.[field] === 'cached').length

  return (
    <div className="drama-phase">
      <div className="drama-shots-header">
        {label}：{doneCount}/{shots.length} 完成
        {cachedCount > 0 && <span style={{ color: 'var(--accent-light)', marginLeft: 8 }}>⚡ {cachedCount} 来自缓存</span>}
        {failedIds.length > 0 && <span style={{ color: 'var(--error)', marginLeft: 8 }}>✗ {failedIds.length} 失败</span>}
      </div>
      {message && <p className="ppt-phase-msg">{message}</p>}
      {stepError && <p className="ppt-error">{stepError}</p>}
      <div className="drama-shot-grid">
        {shots.map(shot => {
          const st = shotStatus[shot.shot_id]?.[field] || 'pending'
          const imgUrl = frames[shot.shot_id]
          return (
            <div key={shot.shot_id} className={`drama-shot-tile ${st}`}>
              {imgUrl
                ? <img src={imgUrl.startsWith('http') ? imgUrl : `${BASE_URL}${imgUrl}`}
                    alt="" className="drama-tile-img"
                    onError={e => { e.target.style.display = 'none' }} />
                : <div className="drama-tile-placeholder">#{shot.shot_id}</div>
              }
              <div className="drama-tile-footer">
                <span className="drama-tile-id">#{shot.shot_id}</span>
                <span className={`ppt-badge anim-${st}`}>
                  {st === 'done' ? `✓ ${label}` : st === 'cached' ? `⚡ ${label}` : st === 'error' ? `✗ ${label}` : `… ${label}`}
                </span>
                <button
                  className="drama-tile-regen"
                  title={`重新生成镜头 ${shot.shot_id}`}
                  disabled={running}
                  onClick={() => onRetry([shot.shot_id])}
                >↺</button>
              </div>
            </div>
          )
        })}
      </div>
      <div className="action-row" style={{ marginTop: 16 }}>
        <button className="btn-secondary" onClick={onBack} disabled={running}>← 上一步</button>
        {failedIds.length > 0 && (
          <button className="btn-secondary" onClick={() => onRetry(failedIds)} disabled={running}>
            重试失败镜头 ({failedIds.length})
          </button>
        )}
        <button className="btn-secondary" onClick={() => onRetry([])} disabled={running}>
          {running ? '生成中...' : '全部重新生成'}
        </button>
        {testRow}
        <button className="btn-primary" onClick={() => onNext()} disabled={running}>
          {nextLabel}
        </button>
      </div>
    </div>
  )
}

// phase order
const PHASES = [
  { id: 'setup',     label: '项目设置' },
  { id: 'script',    label: '剧本生成' },
  { id: 'shots',     label: '分镜拆解' },
  { id: 'keyframes', label: '关键帧' },
  { id: 'dub',       label: '配音' },
  { id: 'lipsync',   label: '口型同步' },
  { id: 'video',     label: '图生视频' },
  { id: 'merge',     label: '合成' },
  { id: 'done',      label: '完成' },
]
const PHASE_IDS = PHASES.map(p => p.id)

const TTS_VOICES = [
  { value: 'zh-CN-YunxiNeural',    label: '云希（男·活泼）' },
  { value: 'zh-CN-YunjianNeural',  label: '云健（男·浑厚）' },
  { value: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女·温柔）' },
  { value: 'zh-CN-XiaoyiNeural',   label: '晓伊（女·活力）' },
]

const GENRES = ['都市爱情', '悬疑推理', '古装武侠', '科幻未来', '家庭伦理', '青春校园', '职场商战']

function emptyChar() {
  return { name: '', gender: 'male', age: 28, appearance: '', personality: '' }
}

export default function StepDrama({ onBack, initialProjectId = null }) {
  const [phase, setPhase]         = useState('setup')
  const [projectId, setProjectId] = useState(initialProjectId)
  const [running, setRunning]     = useState(false)
  const [message, setMessage]     = useState('')
  const [stepError, setStepError] = useState('')

  // setup fields
  const [title, setTitle]               = useState('未命名剧集')
  const [genre, setGenre]               = useState('都市爱情')
  const [plotSummary, setPlotSummary]   = useState('')
  const [style, setStyle]               = useState('写实电影感')
  const [characters, setCharacters]     = useState([emptyChar()])
  const [episode, setEpisode]           = useState(1)

  // pipeline data
  const [script, setScript]     = useState(null)   // {title, episode, scenes:[]}
  const [shots, setShots]       = useState([])     // flat shot list
  const [frames, setFrames]     = useState({})     // {shot_id: image_url}
  const [clips, setClips]       = useState({})     // {shot_id: video_url}
  const [audios, setAudios]     = useState({})     // {shot_id: audio_url}
  const [lipsyncClips, setLipsyncClips] = useState({}) // {shot_id: lipsync_video_url}
  const [finalUrl, setFinalUrl] = useState('')

  // voice settings per character
  const [voiceSettings, setVoiceSettings] = useState({})

  // shot-level status for progress display
  const [shotStatus, setShotStatus] = useState({})  // {shot_id: {kf,vid,dub}}

  // test mode: limit expensive operations to first N shots
  const [testMode, setTestMode] = useState(false)
  const [testLimit, setTestLimit] = useState(3)

  // video provider: 'local' (FFmpeg) | 'jimeng' (Seedance)
  const [videoProvider, setVideoProvider] = useState('local')

  // image provider: 'jimeng' (Seedream) | 'siliconflow' (Kolors)
  const [imageProvider, setImageProvider] = useState('siliconflow')

  // ── restore project ──────────────────────────────────────
  useEffect(() => {
    if (!initialProjectId) return
    dramaGetProject(initialProjectId)
      .then(({ data }) => {
        setTitle(data.title || '未命名剧集')
        setGenre(data.genre || '都市爱情')
        setPlotSummary(data.plot_summary || '')
        setStyle(data.style || '写实电影感')
        setCharacters(data.characters?.length ? data.characters : [emptyChar()])
        setEpisode(data.episode || 1)
        setScript(data.script || null)
        setShots(data.shots || [])
        setFrames(data.frames || {})
        setClips(data.clips || {})
        setAudios(data.audios || {})
        setLipsyncClips(data.lipsync_clips || {})
        setFinalUrl(data.final_url || '')
        setVoiceSettings(data.voice_settings || {})
        setVideoProvider(data.video_provider || 'local')
        setImageProvider(data.image_provider || 'siliconflow')
        // 根据已有数据恢复 shotStatus
        const status = {}
        Object.keys(data.frames || {}).forEach(sid => {
          status[sid] = { ...status[sid], kf: 'cached' }
        })
        Object.keys(data.clips || {}).forEach(sid => {
          status[sid] = { ...status[sid], vid: 'cached' }
        })
        Object.keys(data.audios || {}).forEach(sid => {
          status[sid] = { ...status[sid], dub: 'cached' }
        })
        Object.keys(data.lipsync_clips || {}).forEach(sid => {
          status[sid] = { ...status[sid], lipsync: 'cached' }
        })
        setShotStatus(status)
        setPhase(data.phase || 'setup')
        toast.success('项目已恢复')
      })
      .catch(() => toast.error('项目加载失败'))
  }, [initialProjectId])

  // ── persist helper ───────────────────────────────────────
  const persist = useCallback((patch) => {
    if (!projectId) return
    dramaUpdateProject(projectId, patch).catch(() => {})
  }, [projectId])

  // ── poll helper ──────────────────────────────────────────
  const pollTask = (taskId, onProgress) =>
    poll(
      async () => {
        const { data } = await pollDramaTask(taskId)
        if (data.status === 'running') onProgress?.(data)
        return { data }
      },
      3000, 1800000
    )

  // ── shot status helper ───────────────────────────────────
  const setShotField = (sid, field, value) =>
    setShotStatus(prev => ({ ...prev, [sid]: { ...prev[sid], [field]: value } }))

  // ── character helpers ────────────────────────────────────
  const updateChar = (idx, field, value) =>
    setCharacters(prev => prev.map((c, i) => i === idx ? { ...c, [field]: value } : c))
  const addChar    = () => setCharacters(prev => [...prev, emptyChar()])
  const removeChar = (idx) => setCharacters(prev => prev.filter((_, i) => i !== idx))

  // ── STEP 1: save project info ────────────────────────────
  const handleSetup = async (andNext = false) => {
    setRunning(true)
    setStepError('')
    try {
      const payload = { title, genre, plot_summary: plotSummary, style, characters, episode_count: 1, duration_per_episode: 120 }
      if (projectId) {
        await dramaUpdateProject(projectId, payload)
      } else {
        const { data } = await dramaCreateProject(payload)
        setProjectId(data.project_id)
      }
      if (andNext) {
        setPhase('script')
      } else {
        toast.success('已保存')
      }
    } catch (e) {
      setStepError(e.response?.data?.detail || e.message)
      toast.error('保存失败')
    } finally {
      setRunning(false)
    }
  }

  // ── STEP 2: generate script ──────────────────────────────
  const handleGenScript = async (force = false) => {
    setRunning(true)
    setStepError('')
    setMessage('正在生成剧本...')
    try {
      const { data } = await dramaGenScript(projectId, episode, force)
      if (data.from_cache) {
        setScript(data.script)
        persist({ phase: 'shots' })
        setPhase('shots')
        toast.success('已从缓存加载剧本')
        return
      }
      // 后台任务，轮询
      const result = await pollTask(data.task_id, (d) => setMessage(d.message || '生成中...'))
      setScript(result.result.script)
      persist({ phase: 'shots' })
      setPhase('shots')
      toast.success('剧本生成完成')
    } catch (e) {
      setStepError(e.response?.data?.detail || e.message)
      toast.error('剧本生成失败')
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── STEP 3: split shots ──────────────────────────────────
  const handleGenShots = async (force = false) => {
    if (!script?.scenes?.length) { toast.error('请先生成剧本'); return }
    setRunning(true)
    setStepError('')
    setMessage('正在拆解分镜...')
    try {
      const { data } = await dramaGenShots(projectId, episode, script.scenes, force)
      if (data.from_cache) {
        setShots(data.shots)
        persist({ shots: data.shots, phase: 'keyframes' })
        setPhase('keyframes')
        toast.success('已从缓存加载分镜')
        return
      }
      const result = await pollTask(data.task_id, (d) => setMessage(d.message || '拆解中...'))
      setShots(result.result.shots)
      persist({ shots: result.result.shots, phase: 'keyframes' })
      setPhase('keyframes')
      toast.success(`分镜拆解完成，共 ${result.result.shots.length} 个镜头`)
    } catch (e) {
      setStepError(e.response?.data?.detail || e.message)
      toast.error('分镜拆解失败')
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── STEP 4: generate keyframes ───────────────────────────
  const handleGenKeyframes = async (forceIds = [], limit = 0) => {
    setRunning(true)
    setStepError('')
    const effectiveLimit = limit > 0 ? limit : (testMode ? testLimit : 0)
    const targetShots = effectiveLimit > 0 ? shots.slice(0, effectiveLimit) : shots
    setMessage(effectiveLimit > 0 ? `试跑前 ${effectiveLimit} 帧...` : '正在生成关键帧...')
    try {
      const { data: { task_id } } = await dramaGenKeyframes(projectId, episode, targetShots, forceIds, imageProvider)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '生成中...')
        const fs = data.result?.frames || []
        fs.forEach(f => {
          if (f.image_url) {
            setFrames(prev => {
              const next = { ...prev, [f.shot_id]: f.image_url }
              persist({ frames: next })
              return next
            })
            setShotField(f.shot_id, 'kf', f.from_cache ? 'cached' : 'done')
          }
        })
      })
      const newFrames = {}
      result.result.frames.forEach(f => {
        if (f.image_url) newFrames[f.shot_id] = f.image_url
      })
      setFrames(prev => {
        const next = { ...prev, ...newFrames }
        persist({ frames: next, phase: 'dub' })
        return next
      })
      setPhase('dub')
      toast.success('关键帧全部完成')
    } catch (e) {
      const partial = e.partialResult?.frames || []
      partial.forEach(f => {
        if (f.image_url) {
          setFrames(prev => ({ ...prev, [f.shot_id]: f.image_url }))
          setShotField(f.shot_id, 'kf', 'done')
        }
      })
      setStepError(e.message)
      toast.error(`关键帧生成失败: ${e.message}`)
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── STEP 5: image to video ───────────────────────────────
  const handleGenVideos = async (forceIds = [], limit = 0) => {
    const allShotsWithUrl = shots.map(s => ({ ...s, image_url: frames[s.shot_id] || s.image_url || '' }))
    const effectiveLimit = limit > 0 ? limit : (testMode ? testLimit : 0)
    const targetShots = effectiveLimit > 0 ? allShotsWithUrl.slice(0, effectiveLimit) : allShotsWithUrl
    const missingFrames = targetShots.filter(s => !s.image_url).length
    if (missingFrames > 0 && forceIds.length === 0) {
      toast.error(`${missingFrames} 个镜头缺少关键帧，请先完成关键帧生成`)
      return
    }
    setRunning(true)
    setStepError('')
    setMessage(effectiveLimit > 0 ? `试跑前 ${effectiveLimit} 个视频...` : '正在生成视频片段...')
    try {
      const shotsWithUrl = targetShots
      const { data: { task_id } } = await dramaGenVideos(projectId, episode, shotsWithUrl, forceIds, videoProvider)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '生成中...')
        const cs = data.result?.clips || []
        cs.forEach(c => {
          if (c.video_url) {
            setClips(prev => {
              const next = { ...prev, [c.shot_id]: c.video_url }
              persist({ clips: next })
              return next
            })
            setShotField(c.shot_id, 'vid', c.from_cache ? 'cached' : 'done')
          }
        })
      })
      const newClips = {}
      result.result.clips.forEach(c => {
        if (c.video_url) newClips[c.shot_id] = c.video_url
      })
      setClips(prev => {
        const next = { ...prev, ...newClips }
        persist({ clips: next, phase: 'merge' })
        return next
      })
      setPhase('merge')
      toast.success('视频片段全部完成')
    } catch (e) {
      const partial = e.partialResult?.clips || []
      partial.forEach(c => {
        if (c.video_url) {
          setClips(prev => ({ ...prev, [c.shot_id]: c.video_url }))
          setShotField(c.shot_id, 'vid', 'done')
        }
      })
      setStepError(e.message)
      toast.error(`视频生成失败: ${e.message}`)
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── STEP 6: dubbing ──────────────────────────────────────
  const handleGenDub = async (forceIds = []) => {
    setRunning(true)
    setStepError('')
    setMessage('正在生成配音...')
    const targetShots = testMode ? shots.slice(0, testLimit) : shots
    try {
      const { data: { task_id } } = await dramaGenDub(projectId, episode, targetShots, voiceSettings, forceIds)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '配音中...')
        const as_ = data.result?.audio || []
        as_.forEach(a => {
          if (a.audio_url) {
            setAudios(prev => {
              const next = { ...prev, [a.shot_id]: a.audio_url }
              persist({ audios: next })
              return next
            })
            setShotField(a.shot_id, 'dub', a.from_cache ? 'cached' : 'done')
          }
        })
      })
      const newAudios = {}
      result.result.audio.forEach(a => {
        if (a.audio_url) newAudios[a.shot_id] = a.audio_url
      })
      setAudios(prev => {
        const next = { ...prev, ...newAudios }
        persist({ audios: next, phase: 'lipsync' })
        return next
      })
      setPhase('lipsync')
      toast.success('配音全部完成')
    } catch (e) {
      const partial = e.partialResult?.audio || []
      partial.forEach(a => {
        if (a.audio_url) {
          setAudios(prev => ({ ...prev, [a.shot_id]: a.audio_url }))
          setShotField(a.shot_id, 'dub', 'done')
        }
      })
      setStepError(e.message)
      toast.error(`配音失败: ${e.message}`)
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── STEP 6.5: lipsync ────────────────────────────────────
  const handleGenLipsync = async (forceIds = []) => {
    setRunning(true)
    setStepError('')
    setMessage('正在生成口型同步...')
    const targetShots = testMode ? shots.slice(0, testLimit) : shots
    // 只处理有配音的镜头
    const shotsWithAudio = targetShots.filter(s => audios[s.shot_id])
    if (shotsWithAudio.length === 0) {
      toast('没有需要口型同步的镜头，跳过')
      setPhase('video')
      setRunning(false)
      return
    }
    try {
      const { data: { task_id } } = await dramaGenLipsync(projectId, episode, shotsWithAudio, forceIds)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '口型同步中...')
        const ls = data.result?.lipsync || []
        ls.forEach(l => {
          if (l.video_url) {
            setLipsyncClips(prev => {
              const next = { ...prev, [l.shot_id]: l.video_url }
              persist({ lipsync_clips: next })
              return next
            })
            setShotField(l.shot_id, 'lipsync', l.from_cache ? 'cached' : 'done')
          }
        })
      })
      const newLipsync = {}
      result.result.lipsync.forEach(l => {
        if (l.video_url) newLipsync[l.shot_id] = l.video_url
      })
      setLipsyncClips(prev => {
        const next = { ...prev, ...newLipsync }
        persist({ lipsync_clips: next, phase: 'video' })
        return next
      })
      setPhase('video')
      toast.success('口型同步全部完成')
    } catch (e) {
      const partial = e.partialResult?.lipsync || []
      partial.forEach(l => {
        if (l.video_url) {
          setLipsyncClips(prev => ({ ...prev, [l.shot_id]: l.video_url }))
          setShotField(l.shot_id, 'lipsync', 'done')
        }
      })
      setStepError(e.message)
      toast.error(`口型同步失败: ${e.message}`)
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── STEP 7: merge ────────────────────────────────────────
  const handleMerge = async () => {
    // 验证：有视频的镜头必须有音频（除非该镜头没有台词）
    const shotsWithDialogue = shots.filter(s => s.dialogue)
    const missingAudio = shotsWithDialogue.filter(s => clips[s.shot_id] && !audios[s.shot_id])
    if (missingAudio.length > 0) {
      const ids = missingAudio.map(s => s.shot_id).join(', ')
      toast.error(`镜头 ${ids} 有台词但缺少配音，请先完成配音`)
      setStepError(`镜头 ${ids} 有台词但缺少配音，请返回配音阶段生成`)
      return
    }

    setRunning(true)
    setStepError('')
    setMessage('正在合成视频...')
    const allShots = shots.map(s => ({
      shot_id:   s.shot_id,
      video_url: clips[s.shot_id] || '',
      audio_url: audios[s.shot_id] || '',
    })).sort((a, b) => a.shot_id - b.shot_id)
    const shotsForMerge = testMode ? allShots.slice(0, testLimit) : allShots
    try {
      const { data: { task_id } } = await dramaMerge(projectId, episode, shotsForMerge)
      const result = await pollTask(task_id, (data) => {
        setMessage(data.message || '合成中...')
      })
      setFinalUrl(result.result.video_url)
      persist({ final_url: result.result.video_url, phase: 'done' })
      setPhase('done')
      toast.success('视频合成完毕！')
    } catch (e) {
      setStepError(e.message)
      toast.error(`合成失败: ${e.message}`)
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // ── clear cache ──────────────────────────────────────────
  const handleClearCache = async (scope) => {
    if (!projectId) return
    try {
      await dramaClearCache(projectId, scope)
      toast.success(`已清除 ${scope} 缓存`)
    } catch (e) {
      toast.error('清除缓存失败')
    }
  }

  // ── stepper ──────────────────────────────────────────────
  const currentIdx = PHASE_IDS.indexOf(phase)

  // ── render ───────────────────────────────────────────────
  return (
    <div className="step-panel ppt-panel">
      <div className="ppt-header">
        <h2>真人剧集</h2>
        <button className="btn-ghost" onClick={onBack}>← 返回首页</button>
      </div>

      {/* stepper */}
      <div className="ppt-stepper" style={{ overflowX: 'auto' }}>
        {PHASES.map((p, i) => {
          const state = i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'pending'
          return (
            <div key={p.id} className={`ppt-step ${state}`}>
              <span className="ppt-step-num">{state === 'done' ? '✓' : i + 1}</span>
              <span className="ppt-step-label">{p.label}</span>
            </div>
          )
        })}
      </div>

      {/* 测试模式开关 */}
      {phase !== 'setup' && phase !== 'done' && (
        <div className="drama-test-mode-bar" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={testMode}
              onChange={e => setTestMode(e.target.checked)}
              disabled={running}
            />
            <span>测试模式</span>
          </label>
          {testMode && (
            <>
              <span>只处理前</span>
              <input
                type="number"
                className="drama-input"
                min={1}
                max={shots.length || 10}
                value={testLimit}
                onChange={e => setTestLimit(Math.max(1, parseInt(e.target.value) || 1))}
                style={{ width: 56, textAlign: 'center' }}
                disabled={running}
              />
              <span>个分镜</span>
              <span style={{ color: 'var(--accent-light)', fontSize: 12 }}>（节省文生图/图生视频费用）</span>
            </>
          )}
        </div>
      )}

      {/* 摘要栏 */}
      {phase !== 'setup' && (
        <div className="drama-summary-bar">
          {script && (
            <span className="drama-summary-item">
              剧本：{script.title} · {script.scenes?.length ?? 0} 个场景
            </span>
          )}
          {shots.length > 0 && (
            <span className="drama-summary-item">
              分镜：{shots.length} 个镜头 · 共 {shots.reduce((s, x) => s + (x.duration || 0), 0)}s
            </span>
          )}
          {shots.length > 0 && Object.keys(frames).length > 0 && (
            <span className="drama-summary-item">
              关键帧：{Object.keys(frames).length}/{shots.length} 张
            </span>
          )}
          {shots.length > 0 && Object.keys(clips).length > 0 && (
            <span className="drama-summary-item">
              视频片段：{Object.keys(clips).length}/{shots.length} 个
            </span>
          )}
          {shots.length > 0 && Object.keys(audios).length > 0 && (
            <span className="drama-summary-item">
              配音：{Object.keys(audios).length}/{shots.filter(s => s.dialogue).length} 条
            </span>
          )}
        </div>
      )}

      {stepError && <p className="ppt-error" style={{ margin: '8px 0' }}>{stepError}</p>}
      {message   && <p className="ppt-phase-msg">{message}</p>}

      {/* ── Phase: setup ── */}
      {phase === 'setup' && (
        <div className="drama-setup">
          <div className="drama-field">
            <label>剧集标题</label>
            <input className="drama-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="未命名剧集" />
          </div>
          <div className="drama-field">
            <label>题材</label>
            <select className="model-select" value={genre} onChange={e => setGenre(e.target.value)}>
              {GENRES.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div className="drama-field">
            <label>风格</label>
            <input className="drama-input" value={style} onChange={e => setStyle(e.target.value)} placeholder="写实电影感" />
          </div>
          <div className="drama-field">
            <label>剧情梗概</label>
            <textarea className="drama-textarea" rows={5} value={plotSummary}
              onChange={e => setPlotSummary(e.target.value)}
              placeholder="描述故事背景、主要冲突和情节走向..." />
          </div>

          <div className="drama-section-title">角色设定</div>
          {characters.map((c, idx) => (
            <div key={idx} className="drama-char-card">
              <div className="drama-char-row">
                <input className="drama-input" placeholder="角色名" value={c.name}
                  onChange={e => updateChar(idx, 'name', e.target.value)} style={{ flex: 2 }} />
                <select className="model-select" value={c.gender}
                  onChange={e => updateChar(idx, 'gender', e.target.value)}>
                  <option value="male">男</option>
                  <option value="female">女</option>
                </select>
                <input className="drama-input" type="number" placeholder="年龄" value={c.age}
                  onChange={e => updateChar(idx, 'age', parseInt(e.target.value) || 0)}
                  style={{ width: 70 }} />
                {characters.length > 1 && (
                  <button className="btn-danger-sm" onClick={() => removeChar(idx)}>删除</button>
                )}
              </div>
              <input className="drama-input" placeholder="外貌描述（用于图片生成）" value={c.appearance}
                onChange={e => updateChar(idx, 'appearance', e.target.value)} />
              <input className="drama-input" placeholder="性格特点" value={c.personality}
                onChange={e => updateChar(idx, 'personality', e.target.value)} />
              <div className="drama-char-ref-row" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>参考图：</span>
                {c.ref_url ? (
                  <>
                    <img src={`${BASE_URL}${c.ref_url}`} alt="参考图" style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 4 }} />
                    <button className="btn-secondary btn-sm" onClick={() => updateChar(idx, 'ref_url', '')}>移除</button>
                  </>
                ) : (
                  <input
                    type="file"
                    accept="image/*"
                    onChange={async (e) => {
                      const file = e.target.files?.[0]
                      if (!file || !c.name) return
                      if (!projectId) {
                        toast.error('请先保存项目')
                        return
                      }
                      try {
                        const { data } = await dramaUploadCharacterRef(projectId, c.name, file)
                        updateChar(idx, 'ref_url', data.ref_url)
                        toast.success('参考图已上传')
                      } catch {
                        toast.error('上传失败')
                      }
                    }}
                    style={{ fontSize: 13 }}
                  />
                )}
              </div>
            </div>
          ))}
          <button className="btn-secondary" onClick={addChar} style={{ marginBottom: 16 }}>+ 添加角色</button>

          <div className="action-row">
            <button className="btn-secondary" onClick={() => handleSetup(false)} disabled={running || !plotSummary.trim()}>
              {running ? '保存中...' : '保存'}
            </button>
            <button className="btn-primary" onClick={() => handleSetup(true)} disabled={running || !plotSummary.trim()}>
              下一步：生成剧本 →
            </button>
          </div>
        </div>
      )}

      {/* ── Phase: script ── */}
      {phase === 'script' && (
        <div className="drama-phase">
          {!script ? (
            <div className="drama-empty">
              <p>点击下方按钮，AI 将根据梗概生成完整剧本</p>
              <div className="action-row">
                <button className="btn-secondary" onClick={() => setPhase('setup')}>← 修改设置</button>
                <button className="btn-primary" onClick={() => handleGenScript(false)} disabled={running}>
                  {running ? '生成中...' : '生成剧本'}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="drama-script-view">
                <h3>{script.title} · 第 {script.episode} 集</h3>
                {script.scenes?.map(scene => (
                  <div key={scene.scene_id} className="drama-scene-card">
                    <div className="drama-scene-head">
                      <span className="drama-scene-id">场景 {scene.scene_id}</span>
                      <span className="drama-scene-loc">{scene.location} · {scene.time_of_day}</span>
                    </div>
                    <p className="drama-scene-desc">{scene.description}</p>
                    {scene.dialogues?.map((d, i) => (
                      <div key={i} className="drama-dialogue">
                        <span className="drama-char-name">{d.character}</span>
                        <span className="drama-emotion">[{d.emotion}]</span>
                        <span className="drama-line">{d.line}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div className="action-row" style={{ marginTop: 16 }}>
                <button className="btn-secondary" onClick={() => setPhase('setup')}>← 修改设置</button>
                <button className="btn-secondary" onClick={() => handleGenScript(true)} disabled={running}>
                  {running ? '生成中...' : '重新生成'}
                </button>
                <button className="btn-primary" onClick={() => handleGenShots(false)} disabled={running}>
                  下一步：拆解分镜 →
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Phase: shots ── */}
      {phase === 'shots' && (
        <div className="drama-phase">
          {!shots.length ? (
            <div className="drama-empty">
              <p>将剧本场景拆解为具体拍摄镜头</p>
              <div className="action-row">
                <button className="btn-secondary" onClick={() => setPhase('script')}>← 返回剧本</button>
                <button className="btn-primary" onClick={() => handleGenShots(false)} disabled={running}>
                  {running ? '拆解中...' : '拆解分镜'}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="drama-shots-list">
                <div className="drama-shots-header">
                  共 {shots.length} 个镜头 · 总时长约 {shots.reduce((s, x) => s + (x.duration || 0), 0)} 秒
                </div>
                {shots.map(shot => (
                  <div key={shot.shot_id} className="drama-shot-card">
                    <div className="drama-shot-head">
                      <span className="drama-shot-id">镜头 {shot.shot_id}</span>
                      <span className="drama-shot-meta">{shot.shot_type} · {shot.camera_move} · {shot.duration}s</span>
                      <span className="drama-shot-mood">{shot.mood}</span>
                    </div>
                    {shot.dialogue && (
                      <p className="drama-shot-dialogue">
                        <strong>{shot.characters?.[0]}</strong>：{shot.dialogue}
                      </p>
                    )}
                    <p className="drama-shot-action">{shot.action}</p>
                    <p className="drama-shot-prompt">{shot.image_prompt}</p>
                  </div>
                ))}
              </div>
              <div className="action-row" style={{ marginTop: 16 }}>
                <button className="btn-secondary" onClick={() => setPhase('script')}>← 返回剧本</button>
                <button className="btn-secondary" onClick={() => handleGenShots(true)} disabled={running}>
                  {running ? '拆解中...' : '重新拆解'}
                </button>
                <div className="drama-test-row">
                  <span>图片引擎</span>
                  <select className="model-select" value={imageProvider}
                    onChange={e => { setImageProvider(e.target.value); persist({ image_provider: e.target.value }) }}
                    disabled={running}>
                    <option value="siliconflow">SiliconFlow（Kolors）</option>
                    <option value="jimeng">即梦 AI（Seedream）</option>
                  </select>
                  <span>试跑前</span>
                  <input type="number" className="drama-input" min={1} max={shots.length}
                    value={testLimit} onChange={e => setTestLimit(Math.max(1, parseInt(e.target.value) || 1))}
                    style={{ width: 56, textAlign: 'center' }} />
                  <span>帧</span>
                  <button className="btn-secondary" onClick={() => handleGenKeyframes([], testLimit)} disabled={running}>
                    试跑
                  </button>
                </div>
                <button className="btn-primary" onClick={() => handleGenKeyframes()} disabled={running}>
                  全部生成关键帧 →
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Phase: keyframes ── */}
      {phase === 'keyframes' && (
        <ShotGrid
          shots={shots}
          shotStatus={shotStatus}
          field="kf"
          label="关键帧"
          frames={frames}
          running={running}
          message={message}
          stepError={stepError}
          onBack={() => setPhase('shots')}
          onRetry={(ids) => handleGenKeyframes(ids)}
          onNext={() => handleGenDub()}
          nextLabel="下一步：配音 →"
          testRow={
            <div className="drama-test-row" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span>图片引擎</span>
              <select
                className="model-select"
                value={imageProvider}
                onChange={e => {
                  const v = e.target.value
                  setImageProvider(v)
                  persist({ image_provider: v })
                }}
                disabled={running}
              >
                <option value="siliconflow">SiliconFlow（Kolors）</option>
                <option value="jimeng">即梦 AI（Seedream）</option>
              </select>
            </div>
          }
        />
      )}

      {/* ── Phase: video ── */}
      {phase === 'video' && (
        <ShotGrid
          shots={shots}
          shotStatus={shotStatus}
          field="vid"
          label="视频"
          frames={frames}
          running={running}
          message={message}
          stepError={stepError}
          onBack={() => setPhase('lipsync')}
          onRetry={(ids) => handleGenVideos(ids)}
          onNext={() => handleMerge()}
          nextLabel="下一步：合成 →"
          testRow={
            <div className="drama-test-row" style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span>引擎</span>
                <select
                  className="model-select"
                  value={videoProvider}
                  onChange={e => {
                    const v = e.target.value
                    setVideoProvider(v)
                    persist({ video_provider: v })
                  }}
                  disabled={running}
                >
                  <option value="local">FFmpeg 本地（Ken Burns）</option>
                  <option value="jimeng">即梦 AI（Seedance）</option>
                </select>
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span>试跑前</span>
                <input type="number" className="drama-input" min={1} max={shots.length}
                  value={testLimit} onChange={e => setTestLimit(Math.max(1, parseInt(e.target.value) || 1))}
                  style={{ width: 56, textAlign: 'center' }} />
                <span>个视频</span>
                <button className="btn-secondary" onClick={() => handleGenVideos([], testLimit)} disabled={running}>
                  试跑
                </button>
              </div>
            </div>
          }
        />
      )}

      {/* ── Phase: dub ── */}
      {phase === 'dub' && (
        <div className="drama-phase">
          <div className="drama-voice-settings">
            <div className="drama-section-title">角色配音设置</div>
            {characters.filter(c => c.name).map(c => (
              <div key={c.name} className="drama-voice-row">
                <span className="drama-char-name">{c.name}</span>
                <select className="model-select" value={voiceSettings[c.name] || ''}
                  onChange={e => setVoiceSettings(prev => ({ ...prev, [c.name]: e.target.value }))}>
                  <option value="">自动（按性别）</option>
                  {TTS_VOICES.map(v => <option key={v.value} value={v.value}>{v.label}</option>)}
                </select>
              </div>
            ))}
          </div>
          <ShotGrid
            shots={shots}
            shotStatus={shotStatus}
            field="dub"
            label="配音"
            frames={frames}
            running={running}
            message={message}
            stepError={stepError}
            onBack={() => setPhase('keyframes')}
            onRetry={(ids) => handleGenDub(ids)}
            onNext={() => handleGenLipsync()}
            nextLabel="下一步：口型同步 →"
          />
        </div>
      )}

      {/* ── Phase: lipsync ── */}
      {phase === 'lipsync' && (
        <div className="drama-phase">
          <p style={{ color: 'var(--text-muted)', marginBottom: 12 }}>
            口型同步将关键帧图片 + 配音音频合成为带口型动画的视频片段（使用 SadTalker）。
            没有配音的镜头将跳过，后续使用图生视频处理。
          </p>
          <ShotGrid
            shots={shots}
            shotStatus={shotStatus}
            field="lipsync"
            label="口型"
            frames={frames}
            running={running}
            message={message}
            stepError={stepError}
            onBack={() => setPhase('dub')}
            onRetry={(ids) => handleGenLipsync(ids)}
            onNext={() => { setPhase('video'); }}
            nextLabel="下一步：图生视频 →"
          />
          <div style={{ marginTop: 8 }}>
            <button className="btn-ghost" onClick={() => { setPhase('video'); }} disabled={running}>
              跳过口型同步 →
            </button>
          </div>
        </div>
      )}

      {/* ── Phase: merge ── */}
      {phase === 'merge' && (() => {
        const shotsWithDialogue = shots.filter(s => s.dialogue)
        const missingAudioShots = shotsWithDialogue.filter(s => clips[s.shot_id] && !audios[s.shot_id])
        return (
          <div className="drama-phase">
            <p className="ppt-phase-msg">{message || '准备合成...'}</p>
            {stepError && <p className="ppt-error">{stepError}</p>}
            {missingAudioShots.length > 0 && (
              <div className="drama-missing-audio" style={{ background: 'var(--warning-bg)', padding: 12, borderRadius: 8, marginBottom: 12 }}>
                <p style={{ color: 'var(--warning)', margin: 0 }}>
                  ⚠️ 镜头 {missingAudioShots.map(s => s.shot_id).join(', ')} 有台词但缺少配音
                </p>
                <button
                  className="btn-secondary"
                  style={{ marginTop: 8 }}
                  onClick={() => handleGenDub(missingAudioShots.map(s => s.shot_id))}
                  disabled={running}
                >
                  {running ? '生成中...' : `生成缺失配音 (${missingAudioShots.length} 条)`}
                </button>
              </div>
            )}
            <div className="action-row">
              <button className="btn-secondary" onClick={() => setPhase('video')} disabled={running}>← 返回视频</button>
              <button className="btn-primary" onClick={handleMerge} disabled={running || missingAudioShots.length > 0}>
                {running ? '合成中...' : '开始合成'}
              </button>
            </div>
          </div>
        )
      })()}

      {/* ── Phase: done ── */}
      {phase === 'done' && (
        <div className="drama-phase">
          <div className="ppt-done">
            <p className="ppt-done-label">剧集合成完毕</p>
            <video src={`${BASE_URL}${finalUrl}`} controls className="ppt-preview-video" />
            <div className="action-row">
              <a href={`${BASE_URL}${finalUrl}`} download className="btn-primary">下载视频</a>
              <button className="btn-secondary" onClick={handleMerge} disabled={running}>重新合成</button>
            </div>
          </div>

          <div className="drama-cache-actions">
            <div className="drama-section-title">缓存管理</div>
            <div className="action-row" style={{ flexWrap: 'wrap', gap: 8 }}>
              {['keyframes', 'videos', 'dub', 'all'].map(scope => (
                <button key={scope} className="btn-secondary btn-sm"
                  onClick={() => handleClearCache(scope)}>
                  清除 {scope} 缓存
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
