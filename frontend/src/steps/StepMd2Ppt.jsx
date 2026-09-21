import { useState } from 'react'
import toast from 'react-hot-toast'
import { uploadMarkdown, md2pptSplit, md2pptGenerate, pollMd2PptTask, poll, BASE_URL } from '../api'

const LAYOUT_OPTIONS = [
  { value: 'title', label: '标题页' },
  { value: 'content', label: '内容页' },
  { value: 'code', label: '代码页' },
  { value: 'section', label: '章节页' },
  { value: 'summary', label: '总结页' },
]

export default function StepMd2Ppt({ onBack }) {
  const [phase, setPhase] = useState('upload') // upload | splitting | preview | done
  const [fileId, setFileId] = useState('')
  const [originalFilename, setOriginalFilename] = useState('')
  const [markdown, setMarkdown] = useState('')
  const [slides, setSlides] = useState([])
  const [downloadUrl, setDownloadUrl] = useState('')
  const [outputFilename, setOutputFilename] = useState('')
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState('')

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setRunning(true)
    try {
      const { data } = await uploadMarkdown(file)
      setFileId(data.file_id)
      setOriginalFilename(data.filename)
      setMarkdown(data.content)
      toast.success(`已上传: ${data.filename}`)
    } catch (err) {
      toast.error('上传失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setRunning(false)
    }
  }

  const handleSplit = async () => {
    if (!markdown.trim()) { toast.error('请先上传或粘贴 Markdown 内容'); return }
    setRunning(true)
    setPhase('splitting')
    setMessage('AI 正在分析内容结构...')
    try {
      const { data } = await md2pptSplit(fileId, markdown)
      const result = await poll(
        () => pollMd2PptTask(data.task_id),
        2000, 600000
      )
      setSlides(result.result.slides)
      setPhase('preview')
      toast.success(`拆分完成，共 ${result.result.slides.length} 页`)
    } catch (err) {
      toast.error('拆分失败: ' + err.message)
      setPhase('upload')
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  const handleGenerate = async () => {
    setRunning(true)
    setMessage('正在生成 PPTX...')
    try {
      const { data } = await md2pptGenerate(fileId, slides, originalFilename)
      setDownloadUrl(data.download_url)
      setOutputFilename(data.output_filename || '')
      setPhase('done')
      toast.success('PPTX 生成完成')
    } catch (err) {
      toast.error('生成失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  // Slide editing helpers
  const updateSlide = (idx, field, value) =>
    setSlides(prev => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s))

  const updateBullet = (slideIdx, bulletIdx, value) =>
    setSlides(prev => prev.map((s, i) => {
      if (i !== slideIdx) return s
      const bullets = [...s.bullets]
      bullets[bulletIdx] = value
      return { ...s, bullets }
    }))

  const addBullet = (slideIdx) =>
    setSlides(prev => prev.map((s, i) =>
      i === slideIdx ? { ...s, bullets: [...s.bullets, ''] } : s
    ))

  const removeBullet = (slideIdx, bulletIdx) =>
    setSlides(prev => prev.map((s, i) =>
      i === slideIdx ? { ...s, bullets: s.bullets.filter((_, bi) => bi !== bulletIdx) } : s
    ))

  const addSlide = () =>
    setSlides(prev => [...prev, { slide_id: prev.length + 1, title: '新页面', bullets: [''], notes: '', layout: 'content' }])

  const removeSlide = (idx) =>
    setSlides(prev => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, slide_id: i + 1 })))

  const moveSlide = (idx, dir) => {
    const newIdx = idx + dir
    if (newIdx < 0 || newIdx >= slides.length) return
    setSlides(prev => {
      const arr = [...prev]
      ;[arr[idx], arr[newIdx]] = [arr[newIdx], arr[idx]]
      return arr.map((s, i) => ({ ...s, slide_id: i + 1 }))
    })
  }

  return (
    <div className="step-panel ppt-panel">
      <div className="ppt-header">
        <h2>Markdown 转 PPT</h2>
        <button className="btn-ghost" onClick={onBack}>← 返回首页</button>
      </div>

      {message && <p className="ppt-phase-msg">{message}</p>}

      {phase === 'upload' && (
        <div className="drama-phase">
          <div className="ppt-upload-zone" style={{ marginBottom: 16 }}>
            <p>上传 Markdown 文件，或直接粘贴内容</p>
            <input type="file" accept=".md" onChange={handleUpload} disabled={running} />
          </div>
          <textarea
            className="drama-textarea"
            rows={12}
            value={markdown}
            onChange={e => setMarkdown(e.target.value)}
            placeholder="在此粘贴 Markdown 内容..."
            style={{ fontFamily: 'monospace', fontSize: 13 }}
          />
          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={handleSplit} disabled={running || !markdown.trim()}>
              {running ? '处理中...' : 'AI 智能拆分为幻灯片'}
            </button>
          </div>
        </div>
      )}

      {phase === 'splitting' && (
        <div className="drama-phase" style={{ textAlign: 'center', padding: 40 }}>
          <p>AI 正在分析 Markdown 结构并拆分为幻灯片...</p>
        </div>
      )}

      {phase === 'preview' && (
        <div className="drama-phase">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span>共 {slides.length} 页幻灯片</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn-secondary" onClick={() => setPhase('upload')} disabled={running}>← 重新编辑</button>
              <button className="btn-secondary" onClick={handleSplit} disabled={running}>重新拆分</button>
              <button className="btn-secondary" onClick={addSlide} disabled={running}>+ 添加页面</button>
            </div>
          </div>

          <div className="md2ppt-slides">
            {slides.map((slide, idx) => (
              <div key={idx} className="md2ppt-slide-card">
                <div className="md2ppt-slide-header">
                  <span className="md2ppt-slide-num">#{slide.slide_id}</span>
                  <select className="model-select" value={slide.layout}
                    onChange={e => updateSlide(idx, 'layout', e.target.value)}>
                    {LAYOUT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button className="btn-ghost btn-sm" onClick={() => moveSlide(idx, -1)} disabled={idx === 0}>↑</button>
                    <button className="btn-ghost btn-sm" onClick={() => moveSlide(idx, 1)} disabled={idx === slides.length - 1}>↓</button>
                    <button className="btn-danger-sm" onClick={() => removeSlide(idx)}>删</button>
                  </div>
                </div>
                <input
                  className="drama-input"
                  value={slide.title}
                  onChange={e => updateSlide(idx, 'title', e.target.value)}
                  placeholder="幻灯片标题"
                  style={{ fontWeight: 'bold', marginBottom: 8 }}
                />
                {slide.bullets?.map((bullet, bi) => (
                  <div key={bi} style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                    <span style={{ color: 'var(--text-muted)', lineHeight: '32px' }}>•</span>
                    <input
                      className="drama-input"
                      value={bullet}
                      onChange={e => updateBullet(idx, bi, e.target.value)}
                      style={{ flex: 1 }}
                    />
                    <button className="btn-ghost btn-sm" onClick={() => removeBullet(idx, bi)}>×</button>
                  </div>
                ))}
                <button className="btn-ghost btn-sm" onClick={() => addBullet(idx)} style={{ fontSize: 12 }}>+ 添加要点</button>
              </div>
            ))}
          </div>

          <div className="action-row" style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={handleGenerate} disabled={running || slides.length === 0}>
              {running ? '生成中...' : '生成 PPTX 文件'}
            </button>
          </div>
        </div>
      )}

      {phase === 'done' && (
        <div className="drama-phase" style={{ textAlign: 'center', padding: 40 }}>
          <p style={{ fontSize: 18, marginBottom: 16 }}>PPTX 文件已生成</p>
          <a href={`${BASE_URL}${downloadUrl}`} download={outputFilename || true} className="btn-primary" style={{ display: 'inline-block', padding: '12px 32px' }}>
            下载 PPTX
          </a>
          <div className="action-row" style={{ marginTop: 24, justifyContent: 'center' }}>
            <button className="btn-secondary" onClick={() => setPhase('preview')}>返回编辑</button>
            <button className="btn-secondary" onClick={() => { setPhase('upload'); setSlides([]); setMarkdown(''); }}>新建</button>
          </div>
        </div>
      )}
    </div>
  )
}