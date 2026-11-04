# Referência externa (somente inspeção)

- URL: `https://modsfire.com/RcgUC30KVzcd5Nr?rf=39204`
- Status: **unavailable**
- Exige CSP: **sim** (por isso nenhum arquivo dele é usado).
- Copiado para o mod: **não**.

External mod is used ONLY to inspect folder/file structure and node naming. No mesh, texture, sound, config or binary from it is shipped or committed. All CSP-only files are explicitly excluded.

- Motivo: ModsFire serves a two-step/premium 'Generate Link' page; no direct ZIP could be fetched from the runner. This step is best-effort and non-blocking. The build does NOT depend on it.

---

## Estrutura real de referência: Kunos `formula_k`

Fonte licenciada e **efetivamente consultada** via API do GitHub: `javirs200/acCar` (branch `main`, GPL-3.0). Apenas **nomes de arquivos/pastas** são lidos - nenhum binário, textura, som ou `.kn5` é copiado.

- **155 arquivos** em `EXAMPLE/formula_k/`
- Pastas: `<raiz>`, `animations`, `data`, `sfx`, `skins/formula_K`, `texture`, `texture/flames`, `ui`
- KN5: `collider.kn5`, `formula_K.kn5`, `formula_K_LOD_B.kn5`, `formula_K_LOD_C.kn5`, `formula_k_LOD_D.kn5`
- `animations/`: `CAR_SUSP_LF.ksanim`, `CAR_SUSP_LR.ksanim`, `CAR_SUSP_RF.ksanim`, `CAR_SUSP_RR.ksanim`, `car_shift.ksanim`, `shift.ksanim`, `steer.ksanim`
- Marcadores CSP: **nenhum** (100% vanilla)

### Árvore completa (nomes relativos)

```text
animations/CAR_SUSP_LF.ksanim
animations/CAR_SUSP_LR.ksanim
animations/CAR_SUSP_RF.ksanim
animations/CAR_SUSP_RR.ksanim
animations/car_shift.ksanim
animations/shift.ksanim
animations/steer.ksanim
body_shadow.png
collider.kn5
data/F3hard_front.lut
data/F3hard_rear.lut
data/F3medium_front.lut
data/F3medium_rear.lut
data/F3soft_front.lut
data/F3soft_rear.lut
data/aero.ini
data/ai.ini
data/ambient_shadows.ini
data/blurred_objects.ini
data/brakes.ini
data/cameras.ini
data/car.ini
data/colliders.ini
data/damage.ini
data/dash_cam.ini
data/digital_instruments.ini
data/driver3d.ini
data/drivetrain.ini
data/drs.ini
data/electronics.ini
data/engine.ini
data/escmode.ini
data/final.rto
data/flame_presets.ini
data/flames.ini
data/height_diffuser_CD.lut
data/height_diffuser_CL.lut
data/height_frontwing_CD.lut
data/height_frontwing_CL.lut
data/lights.ini
data/lods.ini
data/mirrors.ini
data/power.lut
data/proview_nodes.ini
data/ratios.rto
data/setup.ini
data/sounds.ini
data/sounds.ini.bak
data/suspension_graphics.ini
data/suspensions.ini
data/tcurve_F3hard.lut
data/tcurve_F3medium.lut
data/tcurve_F3soft.lut
data/throttle.lut
data/tyres (Stefano Casillo's conflicted copy 2020-01-17).ini
data/tyres.ini
data/wing_animations.ini
data/wing_body_AOA_CD.lut
data/wing_body_AOA_CL.lut
data/wing_controller_brake.lut
data/wing_controller_speed.lut
data/wing_diffuser_AOA_CD.lut
data/wing_diffuser_AOA_CL.lut
data/wing_front_AOA_CD.lut
data/wing_front_AOA_CL.lut
data/wing_rear_AOA_CD.lut
data/wing_rear_AOA_CL.lut
data/wing_rearmovable_AOA_CD.lut
data/wing_rearmovable_AOA_CL.lut
driver_base_pos.knh
formula_K.kn5
formula_K_LOD_B.kn5
formula_K_LOD_C.kn5
formula_k_LOD_D.kn5
logo.png
sfx/backfireEXT_1.wav
sfx/backfireEXT_2.wav
sfx/backfireEXT_3.wav
sfx/backfireEXT_4.wav
sfx/backfireEXT_5.wav
sfx/backfireEXT_6.wav
sfx/backfireEXT_7.wav
sfx/backfireEXT_8.wav
sfx/backfireEXT_9.wav
sfx/backfire_1.wav
sfx/backfire_10.wav
sfx/backfire_11.wav
sfx/backfire_12.wav
sfx/backfire_2.wav
sfx/backfire_3.wav
sfx/backfire_4.wav
sfx/backfire_5.wav
sfx/backfire_6.wav
sfx/backfire_7.wav
sfx/backfire_8.wav
sfx/backfire_9.wav
sfx/bodywork.wav
sfx/engine.ini
sfx/engineINT.ini
sfx/ext_fa01_off_2000.wav
sfx/ext_fa01_off_3250.wav
sfx/ext_fa01_off_4250.wav
sfx/ext_fa01_off_5250.wav
sfx/ext_fa01_off_7000.wav
sfx/ext_fa01_on_1500.wav
sfx/ext_fa01_on_4250.wav
sfx/ext_fa01_on_5250.wav
sfx/ext_fa01_on_6000.wav
sfx/ext_fa01_on_6500.wav
sfx/fa01_idle.wav
sfx/fa01_off_2250.wav
sfx/fa01_off_3500.wav
sfx/fa01_off_4500.wav
sfx/fa01_off_6500.wav
sfx/fa01_on_2250.wav
sfx/fa01_on_3750.wav
sfx/fa01_on_4500.wav
sfx/fa01_on_5000.wav
sfx/fa01_on_6500.wav
sfx/formula_k.bank
sfx/geardn.wav
sfx/geardnEXT.wav
sfx/gearup.wav
sfx/gearupEXT.wav
sfx/transmission.wav
sfx/turbo.wav
skins/formula_K/GOMMA_BASE_dirt3.dds
skins/formula_K/Protection.dds
skins/formula_K/SkinBase.dds
skins/formula_K/livery.png
skins/formula_K/preview.jpg
skins/formula_K/ui_skin.json
texture/display.png
texture/display_off.png
texture/flames/7.png
texture/flames/8.png
texture/flames/f2.dds
texture/flames/f3.dds
texture/flames/f4.dds
texture/flames/l3.dds
texture/flames/l4.dds
texture/flames/l6.dds
texture/flames/x0.dds
texture/flames/x1.dds
texture/flames/x5.dds
texture/flames/x7.dds
texture/flames/x8.dds
tyre_0_shadow.png
tyre_1_shadow.png
tyre_2_shadow.png
tyre_3_shadow.png
ui/badge.png
ui/old_badge.png
ui/preview_small.png
ui/ui_car.json
```

O nosso `content/cars/arb_rb20/` espelha essa árvore. Diferenças deliberadas: sem `driver_base_pos.knh`, `data/flames.ini`/`texture/flames/*`, `data/analog_instruments.ini` e `animations/shift.ksanim` (formatos auto-carregados que não podemos validar sem o AC e que foram removidos na correção de crash) e sem o banco FMOD `.bank` proprietário. Nenhum arquivo CSP.

