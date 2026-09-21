import { useState, useRef } from 'react'
import toast from 'react-hot-toast'
import { uploadPortrait } from '../api'

export default function StepPortrait({ onDone }) {
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [description, setDescription] = useState('35岁中国男性讲师，短黑发，穿深色西装，表情自信专业，面向镜头站立讲解，简洁明亮的演播室背景')
  const inputRef = useRef()

  const handleFile = (file) => {
    if (!file) return
    const url = URL.createObjectURL(file)
    setPreview({ file, url })
  }

  const handleDrop = (e) => {
    e.preventDefault()
    handleFile(e.dataTransfer.files[0])
  }

  const handleSubmit = async () => {
    if (!preview) return toast.error('请先选择形象图片')
    if (!description.trim()) return toast.error('请填写人物外貌描述')
    setLoading(true)
    try {
      const { data } = await uploadPortrait(preview.file)
      toast.success('形象上传成功')
      onDone({ ...data, description: description.trim() })
    } catch (e) {
      toast.error(`上传失败: ${e.response?.data?.detail || e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="step-panel">
      <h2>第一步：上传个人形象图</h2>
      <p className="step-desc">上传人物照片，并填写外貌描述，AI 将在每个分镜中生成该人物讲解的画面。</p>

      <div
        className="dropzone"
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
        onClick={() => inputRef.current.click()}
      >
        {preview ? (
          <img src={preview.url} alt="preview" className="portrait-preview" />
        ) : (
          <div className="dropzone-hint">
            <span className="icon-upload">↑</span>
            <p>点击或拖拽上传图片</p>
            <p className="small">支持 JPG / PNG / WEBP，最大 50MB</p>
          </div>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => handleFile(e.target.files[0])}
      />

      {preview && (
        <>
          <div className="portrait-desc-block">
            <label className="portrait-desc-label">
              人物外貌描述（将自动翻译后注入每个分镜的图片提示词）
            </label>
            <textarea
              className="portrait-desc-input"
              rows={3}
              placeholder="例如：35岁中国男性教师，短黑发，穿白衬衫，表情自信专业，站在白板前讲课"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <p className="portrait-desc-hint">
              描述越详细，人物在每个镜头中的一致性越高。建议包含：年龄、发型、服装、表情、动作。
            </p>
          </div>
          <div className="action-row">
            <button className="btn-secondary" onClick={() => setPreview(null)}>重新选择</button>
            <button className="btn-primary" onClick={handleSubmit} disabled={loading}>
              {loading ? '上传中...' : '下一步'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
