---
name: image-hash
description: Computes perceptual image hash (dHash) and finds visually similar images in the moderation database. Use to detect reposted/edited violation images that bypass exact-match filters.
---

# Image Hash (Perceptual Hashing)

## Overview
Difference Hash (dHash) for perceptual image deduplication. Detects visually similar images even after resizing, compression, or minor edits.

## Algorithm
1. Resize to 9×8 grayscale
2. Compute row-wise pixel differences (dHash)
3. Generate 64-bit hash fingerprint
4. Compare using Hamming distance

## Thresholds
- Hamming distance < 5: Near-identical (same image, different compression)
- Hamming distance 5-10: Visually similar (cropped, resized, watermarked)
- Hamming distance > 10: Different images

## Integration
```python
from mcp_servers.tools.image_hash import ImageHashTool
tool = ImageHashTool()
result = await tool.execute(image_bytes, threshold=10)
```
