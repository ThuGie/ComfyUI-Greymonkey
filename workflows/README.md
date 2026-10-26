# Influencer workflows — original MOSS

Open either JSON in ComfyUI. The simple workflow configures one adult creator; the advanced workflow exposes individual appearance, garment, accessory and owned-object details. They require a current ComfyUI with native MOSS support plus ComfyUI-Greymonkey. Model weights are not included.

## Files selected in the examples

| Component | Selected local filename | ComfyUI folder |
| --- | --- | --- |
| Original MOSS SFT diffusion model | `moss_image_sft_int8_convrot.safetensors` | `models/diffusion_models/moss/` |
| 8-step DMD acceleration adapter | `MOSS_Image_SFT_8_steps_dmd_v0.1.safetensors` | `models/loras/moss/` |
| MOSS text encoder | `qwen3.5_9b_moss_image_sft_w4a8_gptq.safetensors` | `models/text_encoders/` |
| Matching MOSS VAE | `moss_image_vae_bf16.safetensors` | `models/vae/` |

Choose your matching filenames when your installation uses different names or quantizations. These examples use original SFT with the acceleration adapter, not Moody or an unrelated style checkpoint. Do not add another acceleration adapter to an already merged Turbo checkpoint.

## Sampling and connections

- Native UNETLoader → 8-step DMD LoraLoaderModelOnly (strength 1) → KSampler.
- Native CLIPLoader: type `moss_image`; the Greymonkey positive and negative outputs have separate encoders.
- EmptyFlux2LatentImage: 768 × 1024, batch size 1.
- KSampler: 8 steps, CFG 1, Euler, simple, full denoise.
- Native MOSS sampling is retained. No SD3 sampling override or skip-layer patch is added.
- At CFG 1 conventional negative conditioning is inactive; that encoder is labelled accordingly. A different sampling configuration requires the checkpoint/adapter's own settings.
- Decode → Greymonkey Save Image. The structured generation_result connection preserves the scene, prompt and workflow metadata.

## Advanced detail chains

The subject chain contains age, build, hair texture/style/parting, eyes, wink expression, makeup, gaze, hoodie, layering, jeans, an optional bracelet and body language. Change each detail's own color where available. Hair color is on Scene Subject. Creator Settings controls category/presentation; explicit details take priority over random filling.

The object chain contains material, surface finish, colored controls, casing and grip → Scene Object → Scene Subject.object_settings. Scene Subject's legacy Related Object and Relationship remain None, preventing duplicate specification. To add a second independently configured object, add it as another scene subject and target it with the existing relationship system.

Prompt generation calls the configured Greymonkey service. Latent dimensions and sampling are controlled by the actual image nodes, not by the generator's suggested settings. Save a copy before experimenting. Both final workflows completed successfully in real ComfyUI using original SFT + DMD at 768 × 1024. The optional bracelet is disconnected by default; connect it only with compatible wrist visibility. Generated portraits are held back from the public repository.
