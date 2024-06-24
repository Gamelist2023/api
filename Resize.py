from PIL import Image

def resize_image(input_image_path, output_image_path, size):
    original_image = Image.open(input_image_path)
    width, height = original_image.size
    print(f"The original image size is {width} wide x {height} tall")

    resized_image = original_image.resize(size)
    width, height = resized_image.size
    print(f"The resized image size is {width} wide x {height} tall")
    resized_image.show()
    resized_image.save(output_image_path)

# iPhone 12 Pro Maxの解像度に合わせて画像をリサイズ
resize_image('home\css\AIchat.png', 'resized_image_iPhone11ProMax.png', (414, 896))
resize_image('home\css\AIchat.png', 'resized_image_iPhone11.png', (414, 896))
resize_image('home\css\AIchat.png', 'resized_image_iPhone8plus.png', (414, 736))
resize_image('home\css\AIchat.png', 'resized_image_iPhone8.png', (375, 667))
resize_image('home\css\AIchat.png', 'resized_image_iPhoneSEold.png', (320, 568))




