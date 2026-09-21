import { useState, useRef } from 'react'
import toast from 'react-hot-toast'
import { uploadArticle } from '../api'

export default function StepArticle({ onDone, portrait }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState('')
  const [loading, setLoading] = useState(false)
  const inputRef = useRef()

  const handleFile = async (f) => {
    if (!f) return
    setFile(f)
    const text = await f.text()
    setPreview(text.slice(0, 1000))
  }

  const handleDrop = (e) => {
    e.preventDefault()
    handleFile(e.dataTransfer.files[0])
  }

  const handleSubmit = async () => {
    if (!file) return toast.error('请先选择文章文件')
    setLoading(true)
    try {
      const { data } = await uploadArticle(file)
      toast.success('文章上传成功')
      onDone(data)
    } catch (e) {
      toast.error(`上传失败: ${e.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="step-panel">
      <h2>第二步：上传文章</h2>
      <p className="step-desc">上传要转化为视频的文章，支持 .txt / .md 格式。</p>

      <div
        className="dropzone text-dropzone"
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => !file && inputRef.current.click()}
      >
        {preview ? (
          <pre className="article-preview">{preview}{preview.length >= 1000 ? '\n...' : ''}</pre>
        ) : (
          <div className="dropzone-hint">
            <span className="icon-upload">↑</span>
            <p>点击或拖拽上传文章</p>
            <p className="small">支持 .txt / .md</p>
          </div>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".txt,.md"
        hidden
        onChange={(e) => handleFile(e.target.files[0])}
      />

      {file && (
        <div className="action-row">
          <button className="btn-secondary" onClick={() => { setFile(null); setPreview('') }}>重新选择</button>
          <button className="btn-primary" onClick={handleSubmit} disabled={loading}>
            {loading ? '上传中...' : '下一步'}
          </button>
        </div>
      )}
    </div>
  )
}
