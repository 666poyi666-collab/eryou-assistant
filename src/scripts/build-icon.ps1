[CmdletBinding()]
param(
    [string]$Output = (Join-Path $PSScriptRoot '..\assets\eryou_assistant_icon.ico')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function New-IconPng([int]$Size) {
    $bitmap = New-Object System.Drawing.Bitmap(
        $Size,
        $Size,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $stream = New-Object System.IO.MemoryStream
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.ScaleTransform([single]($Size / 256.0), [single]($Size / 256.0))

        $path.AddArc(0, 0, 112, 112, 180, 90)
        $path.AddArc(144, 0, 112, 112, 270, 90)
        $path.AddArc(144, 144, 112, 112, 0, 90)
        $path.AddArc(0, 144, 112, 112, 90, 90)
        $path.CloseFigure()
        $graphics.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 18, 37, 44))), $path)

        $graphics.DrawEllipse(
            (New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 53, 197, 138), 16)),
            52, 52, 152, 152
        )
        $accentPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 242, 166, 90), 10)
        $accentPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $accentPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $graphics.DrawLine($accentPen, 128, 54, 128, 76)
        $graphics.DrawLine($accentPen, 128, 180, 128, 202)
        $graphics.DrawLine($accentPen, 54, 128, 76, 128)
        $graphics.DrawLine($accentPen, 180, 128, 202, 128)

        $graphics.FillPolygon(
            (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 53, 197, 138))),
            [System.Drawing.PointF[]]@(
                [System.Drawing.PointF]::new(128, 78),
                [System.Drawing.PointF]::new(156, 150),
                [System.Drawing.PointF]::new(128, 137),
                [System.Drawing.PointF]::new(100, 150)
            )
        )
        $graphics.FillPolygon(
            (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 216, 255, 240))),
            [System.Drawing.PointF[]]@(
                [System.Drawing.PointF]::new(128, 78),
                [System.Drawing.PointF]::new(100, 150),
                [System.Drawing.PointF]::new(128, 137)
            )
        )
        $graphics.FillEllipse(
            (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 242, 166, 90))),
            113, 113, 30, 30
        )
        $graphics.FillEllipse(
            (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 18, 37, 44))),
            121, 121, 14, 14
        )
        $routePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 111, 183, 255), 7)
        $routePen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
        $routePen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
        $graphics.DrawLine($routePen, 177, 80, 160, 97)
        $graphics.FillEllipse(
            (New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 111, 183, 255))),
            175, 58, 24, 24
        )

        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return ,$stream.ToArray()
    }
    finally {
        $stream.Dispose()
        $path.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$sizes = @(16, 24, 32, 48, 64, 128, 256)
$images = @($sizes | ForEach-Object { New-IconPng $_ })
$outputPath = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($outputPath)) | Out-Null
$container = New-Object IO.MemoryStream
$writer = New-Object IO.BinaryWriter($container)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$sizes.Count)
    $offset = 6 + (16 * $sizes.Count)
    for ($index = 0; $index -lt $sizes.Count; $index++) {
        $size = $sizes[$index]
        $width = if ($size -eq 256) { 0 } else { $size }
        $writer.Write([byte]$width)
        $writer.Write([byte]$width)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$images[$index].Length)
        $writer.Write([uint32]$offset)
        $offset += $images[$index].Length
    }
    foreach ($image in $images) {
        $writer.Write($image)
    }
    [IO.File]::WriteAllBytes($outputPath, $container.ToArray())
}
finally {
    $writer.Dispose()
    $container.Dispose()
}
Write-Output $outputPath
