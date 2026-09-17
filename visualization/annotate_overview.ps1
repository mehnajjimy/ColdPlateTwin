param(
    [string]$InputPath = "$PSScriptRoot\render_output\experiment_overview_clean.png",
    [string]$OutputPath = "$PSScriptRoot\render_output\experiment_overview.png"
)

Add-Type -AssemblyName System.Drawing
$source = [System.Drawing.Image]::FromFile($InputPath)
$canvas = New-Object System.Drawing.Bitmap $source.Width, $source.Height
$g = [System.Drawing.Graphics]::FromImage($canvas)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$g.DrawImage($source, 0, 0, $source.Width, $source.Height)

$ink = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::Black)
$paper = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
$border = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 3
$arrow = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 4
$font = New-Object System.Drawing.Font ('Arial', 23, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$titleFont = New-Object System.Drawing.Font ('Arial', 34, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$format = New-Object System.Drawing.StringFormat
$format.Alignment = [System.Drawing.StringAlignment]::Center
$format.LineAlignment = [System.Drawing.StringAlignment]::Center

function Draw-Callout($Text, $X, $Y, $AnchorX, $AnchorY) {
    $size = $g.MeasureString($Text, $font)
    $w = [math]::Ceiling($size.Width + 30)
    $h = 48
    $rect = [System.Drawing.RectangleF]::new([single]$X, [single]$Y, [single]$w, [single]$h)
    $g.FillRectangle($paper, $rect)
    $g.DrawRectangle($border, $X, $Y, $w, $h)

    $cx = $X + $w / 2; $cy = $Y + $h / 2
    $dx = $AnchorX - $cx; $dy = $AnchorY - $cy
    if ([math]::Abs($dx / ($w / 2)) -gt [math]::Abs($dy / ($h / 2))) {
        $sx = if ($dx -ge 0) { $X + $w } else { $X }
        $sy = $cy + ($dy * ($w / 2) / [math]::Max([math]::Abs($dx), 1))
    } else {
        $sx = $cx + ($dx * ($h / 2) / [math]::Max([math]::Abs($dy), 1))
        $sy = if ($dy -ge 0) { $Y + $h } else { $Y }
    }
    $g.DrawLine($arrow, $sx, $sy, $AnchorX, $AnchorY)
    $angle = [math]::Atan2($AnchorY - $sy, $AnchorX - $sx)
    $backX = $AnchorX - 15 * [math]::Cos($angle); $backY = $AnchorY - 15 * [math]::Sin($angle)
    $perpX = 7 * [math]::Sin($angle); $perpY = 7 * -[math]::Cos($angle)
    [System.Drawing.PointF[]]$points = @(
        [System.Drawing.PointF]::new([single]$AnchorX, [single]$AnchorY),
        [System.Drawing.PointF]::new([single]($backX + $perpX), [single]($backY + $perpY)),
        [System.Drawing.PointF]::new([single]($backX - $perpX), [single]($backY - $perpY))
    )
    $g.FillPolygon($ink, $points)
    $g.DrawString($Text, $font, $ink, $rect, $format)
}

# Title and compact, direct functional callouts. Coordinates are in final 1920×1080 pixels.
$title = 'COLDPLATE TWIN — PROPOSED EXPERIMENTAL ARRANGEMENT'
$titleSize = $g.MeasureString($title, $titleFont)
$titleRect = [System.Drawing.RectangleF]::new([single]((1920 - $titleSize.Width - 44) / 2), [single]24, [single]($titleSize.Width + 44), [single]58)
$g.FillRectangle($paper, $titleRect); $g.DrawRectangle($border, $titleRect.X, $titleRect.Y, $titleRect.Width, $titleRect.Height)
$g.DrawString($title, $titleFont, $ink, $titleRect, $format)

Draw-Callout 'Reservoir' 36 180 274 392
Draw-Callout 'Pump' 36 270 385 465
Draw-Callout 'Control valve' 36 360 536 488
Draw-Callout 'Flow meter' 36 450 654 522
Draw-Callout 'Tin PT100' 36 540 812 548
Draw-Callout 'Coldplate test article' 36 630 1005 555
Draw-Callout 'IR camera' 1660 180 1030 284
Draw-Callout 'Tout PT100' 1660 270 1110 600
Draw-Callout 'Heat rejector' 1660 360 1190 715
Draw-Callout 'Δp sensor' 1660 450 1435 540
Draw-Callout 'Logger' 1660 540 1670 645
Draw-Callout 'Heater supply • 24 VDC' 1595 630 1665 775

$key = 'blue = water route   •   amber = heater power   •   teal = data / Δp sense'
$keySize = $g.MeasureString($key, $font)
$keyRect = [System.Drawing.RectangleF]::new([single]((1920 - $keySize.Width - 36) / 2), [single]1005, [single]($keySize.Width + 36), [single]46)
$g.FillRectangle($paper, $keyRect); $g.DrawRectangle($border, $keyRect.X, $keyRect.Y, $keyRect.Width, $keyRect.Height)
$g.DrawString($key, $font, $ink, $keyRect, $format)

$canvas.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
$font.Dispose(); $titleFont.Dispose(); $ink.Dispose(); $paper.Dispose(); $border.Dispose(); $arrow.Dispose(); $g.Dispose(); $canvas.Dispose(); $source.Dispose()
