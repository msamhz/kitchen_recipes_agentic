const MAX_BYTES = 4_000_000 // 4 MB — safe under API Gateway + Lambda 6 MB cap

export async function compressImage(file) {
  if (file.size <= MAX_BYTES) return file

  return new Promise((resolve) => {
    const img = new Image()
    const url = URL.createObjectURL(file)

    img.onload = () => {
      URL.revokeObjectURL(url)

      const canvas = document.createElement('canvas')
      let { width, height } = img
      const MAX_DIM = 1600
      if (width > height && width > MAX_DIM) {
        height = Math.round(height * MAX_DIM / width)
        width = MAX_DIM
      } else if (height >= width && height > MAX_DIM) {
        width = Math.round(width * MAX_DIM / height)
        height = MAX_DIM
      }

      canvas.width = width
      canvas.height = height
      canvas.getContext('2d').drawImage(img, 0, 0, width, height)

      const attempt = (quality) => {
        canvas.toBlob(
          (blob) => {
            if (!blob) return resolve(file)
            if (blob.size <= MAX_BYTES || quality <= 0.3) {
              resolve(new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' }))
            } else {
              attempt(Math.round((quality - 0.15) * 100) / 100)
            }
          },
          'image/jpeg',
          quality,
        )
      }
      attempt(0.82)
    }

    img.onerror = () => resolve(file)
    img.src = url
  })
}
