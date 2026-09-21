import { useState } from 'react'
import toast from 'react-hot-toast'
import { uploadPdfToWord, pdfToWordConvert, pollPdfToWordTask, poll, BASE_URL } from '../api'

export default function StepPdf2Word({ onBack }) {
  const [phase, setPhase] = useState('upload')
  const [fileId, setFileId] = useState('')
  const [filename, setFilename] = useState('')
  const [downloadUrl, setDownloadUrl] = useState('')
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState('')
  const [meta, setMeta] = useState(null)

  const reset = () => {
    setPhase('upload')
    setFileId('')
    setFilename('')
    setDownloadUrl('')
    setMessage('')
    setMeta(null)
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setRunning(true)
    try {
      const { data } = await uploadPdfToWord(file)
      setFileId(data.file_id)
      setFilename(data.filename)
      setDownloadUrl('')
      setMeta(null)
      toast.success(`已上传: ${data.filename}`)
    } catch (err) {
      toast.error('上传失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setRunning(false)
    }
  }

  const handleConvert = async () => {
    if (!fileId) {
      toast.error('请先上传 PDF 文件')
      return
    }
    setRunning(true)
    setPhase('converting')
    setMessage('正在分析 PDF，并自动识别扫描页或图片中的文字...')
    try {
      const { data } = await pdfToWordConvert(fileId)
      const result = await poll(() => pollPdfToWordTask(data.task_id), 2000, 600000)
      setDownloadUrl(result.result.download_url)
      setMeta({
        pageCount: result.result.page_count,
        ocrPages: result.result.ocr_pages || [],
        mode: result.result.mode,
      })
      setPhase('done')
      toast.success(result.message || 'Word 文档生成完成')
    } catch (err) {
      toast.error('转换失败: ' + (err.response?.data?.detail || err.message))
      setPhase('upload')
    } finally {
      setRunning(false)
      setMessage('')
    }
  }

  return (
    <div className="step-panel ppt-panel">
      <div className="ppt-header">
        <h2>PDF 转 Word</h2>
        <button className="btn-ghost" onClick={onBack}>← 返回首页</button>
      </div>

      {message && <p className="ppt-phase-msg">{message}</p>}

      {phase === 'upload' && (
        <div className="drama-phase">
          <div className="ppt-upload-zone" style={{ marginBottom: 16 }}>
            <p>上传 PDF，自动识别扫描页或图片中的文字，并写入可编辑 Word 文档</p>
            <input type="file" accept=".pdf,application/pdf" onChange={handleUpload} disabled={running} />
          </div>
          {filename && (
            <p className="muted" style={{ marginBottom: 16 }}>当前文件：{filename}</p>
          )}
          <div className="action-row">
            <button className="btn-primary" onClick={handleConvert} disabled={running || !fileId}>
              {running ? '处理中...' : '转换为 Word'}
            </button>
            {fileId && (
              <button className="btn-secondary" onClick={reset} disabled={running}>
                重新选择
              </button>
            )}
          </div>
        </div>
      )}

      {phase === 'converting' && (
        <div className="drama-phase" style={{ textAlign: 'center', padding: 40 }}>
          <p>正在转换，请稍候...</p>
        </div>
      )}

      {phase === 'done' && (
        <div className="drama-phase" style={{ textAlign: 'center', padding: 40 }}>
          <p style={{ fontSize: 18, marginBottom: 16 }}>Word 文档已生成</p>
          {meta && (
            <div className="muted" style={{ marginBottom: 16 }}>
              <div>总页数：{meta.pageCount ?? '-'}</div>
              <div>OCR 页数：{meta.ocrPages?.length ?? 0}</div>
              <div>输出模式：{meta.mode === 'ocr_rebuilt' ? 'OCR 重建' : '直接转换'}</div>
            </div>
          )}
          <a href={`${BASE_URL}${downloadUrl}`} download className="btn-primary" style={{ display: 'inline-block', padding: '12px 32px' }}>
            下载 Word 文档
          </a>
          <div className="action-row" style={{ marginTop: 24, justifyContent: 'center' }}>
            <button className="btn-secondary" onClick={reset}>新建转换</button>
          </div>
        </div>
      )}
    </div>
  )
}
