import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

def create_app_icon():
    # 512x512 master high-res image
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Outer Glow / Shadow
    glow_box = [32, 32, 480, 480]
    draw.rounded_rectangle(glow_box, radius=110, fill=(0, 229, 180, 40))
    img = img.filter(ImageFilter.GaussianBlur(radius=12))
    draw = ImageDraw.Draw(img)

    # 2. Main Squircle Body (Dark sleek glass)
    body_box = [48, 48, 464, 464]
    draw.rounded_rectangle(body_box, radius=100, fill=(13, 17, 23, 250), outline=(0, 229, 180, 220), width=8)

    # 3. Inner neon ring / accent
    inner_ring = [66, 66, 446, 446]
    draw.rounded_rectangle(inner_ring, radius=86, fill=None, outline=(0, 229, 180, 60), width=3)

    # 4. Neon Play Icon (Video Stream)
    # Coordinates of sleek play triangle pointing right
    triangle = [
        (205, 160),  # Top left
        (355, 256),  # Right point
        (205, 352)   # Bottom left
    ]
    # Play icon glow
    draw.polygon(triangle, fill=(0, 229, 180, 255))
    
    # Inner bright play accent
    inner_tri = [
        (225, 195),
        (325, 256),
        (225, 317)
    ]
    draw.polygon(inner_tri, fill=(180, 255, 240, 255))

    # 5. P2P Mesh dots / stream rays (small high-tech accent dots)
    dots = [(375, 180), (395, 256), (375, 332)]
    for dx, dy in dots:
        draw.ellipse([dx-10, dy-10, dx+10, dy+10], fill=(0, 229, 180, 240))

    ico_path = os.path.join(ASSETS_DIR, "app_icon.ico")
    png_path = os.path.join(ASSETS_DIR, "app_icon.png")
    img.save(png_path, format="PNG")
    
    # Save as multi-resolution ICO
    img.save(
        ico_path, 
        format="ICO", 
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print(f"[*] app_icon.ico olusturuldu: {ico_path}")

def create_pack_icon():
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Outer Glow
    glow_box = [32, 32, 480, 480]
    draw.rounded_rectangle(glow_box, radius=110, fill=(139, 92, 246, 50))
    img = img.filter(ImageFilter.GaussianBlur(radius=12))
    draw = ImageDraw.Draw(img)

    # 2. Main Squircle Body
    body_box = [48, 48, 464, 464]
    draw.rounded_rectangle(body_box, radius=100, fill=(18, 16, 28, 250), outline=(139, 92, 246, 220), width=8)

    # 3. Package / Cube Icon
    # Isometric cube lines
    center_x, center_y = 256, 256
    top_face = [
        (256, 140),
        (350, 195),
        (256, 250),
        (162, 195)
    ]
    draw.polygon(top_face, fill=(168, 85, 247, 240), outline=(216, 180, 254, 255), width=4)

    left_face = [
        (162, 195),
        (256, 250),
        (256, 370),
        (162, 315)
    ]
    draw.polygon(left_face, fill=(126, 34, 206, 240), outline=(192, 132, 252, 255), width=4)

    right_face = [
        (256, 250),
        (350, 195),
        (350, 315),
        (256, 370)
    ]
    draw.polygon(right_face, fill=(91, 33, 182, 240), outline=(168, 85, 247, 255), width=4)

    ico_path = os.path.join(ASSETS_DIR, "pack_icon.ico")
    png_path = os.path.join(ASSETS_DIR, "pack_icon.png")
    img.save(png_path, format="PNG")
    img.save(
        ico_path, 
        format="ICO", 
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print(f"[*] pack_icon.ico olusturuldu: {ico_path}")

if __name__ == "__main__":
    create_app_icon()
    create_pack_icon()
