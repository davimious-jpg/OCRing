from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

from .models import PreprocessedRegion, PreprocessVariant, Rect


def preprocess_inventory_region(image_path: Path, region: Rect) -> tuple[PreprocessedRegion, ...]:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        variants = preprocess_field_crop(rgb, region)
        return tuple(
            PreprocessedRegion(
                variant=variant.variant,
                region=region,
                width=variant.width,
                height=variant.height,
                stats=variant.stats,
            )
            for variant in variants
        )


def preprocess_field_crop(image: Image.Image, region: Rect) -> tuple[PreprocessedRegion, ...]:
    crop = image.crop((region.x1, region.y1, region.x2, region.y2))
    variants = {
        PreprocessVariant.GRAYSCALE: crop.convert("L"),
        PreprocessVariant.HIGH_CONTRAST: ImageEnhance.Contrast(crop.convert("L")).enhance(1.8),
        PreprocessVariant.SHARPENED: crop.convert("L").filter(ImageFilter.SHARPEN),
    }

    return tuple(
        PreprocessedRegion(
            variant=variant,
            region=region,
            width=variant_image.width,
            height=variant_image.height,
            stats=_image_stats(variant_image),
        )
        for variant, variant_image in variants.items()
    )


def _image_stats(image: Image.Image) -> dict[str, float]:
    stat = ImageStat.Stat(image)
    mean = float(stat.mean[0]) if stat.mean else 0.0
    stddev = float(stat.stddev[0]) if stat.stddev else 0.0
    extrema = stat.extrema[0] if stat.extrema else (0, 0)
    return {
        "mean_luma": round(mean, 3),
        "stddev_luma": round(stddev, 3),
        "min_luma": float(extrema[0]),
        "max_luma": float(extrema[1]),
    }
