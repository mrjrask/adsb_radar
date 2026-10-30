# Manual artwork upload guide

No images have been copied. These empty folders match the source Desk Display artwork layout. Upload your existing PNG files at their original paths, then pull the repo on the Pi and rerun the installer.

## Airline logos

Upload logos to `images/air/<ICAO>.png`, for example `DAL.png`, `UAL.png`, `AAL.png`, and `SWA.png`. Transparent PNG is preferred; JPG/JPEG are also accepted. The lookup uses the airline ICAO code, not its two-letter IATA code.

## Aircraft illustrations

Upload transparent, high-resolution side-view PNGs to `images/aircraft/<ICAO>/<TYPE>.png`. Use the original files from desk_display; keep their aspect ratio and transparency. The renderer trims transparent margins and scales to the native layout. For sharp 4K display, prefer aircraft artwork at least 1500 pixels wide when available.

Lookup order is exact airline/type, a sibling type in the same aircraft family, exact `_generic` type, sibling `_generic` type, then the procedural illustration. Missing logos use an airline badge. No external image downloads occur during installation or runtime.

### Existing filenames to upload

This list was generated from source paths only, without reading or copying image data. Upload whichever airlines/types you want; every file is optional. Additional ICAO folders and types can be added later.

| Folder | PNG filenames |
| --- | --- |

| `images/aircraft/AAL/` | `A21N.png`, `A319.png`, `A320.png`, `A321.png`, `B38M.png`, `B738.png`, `B772.png`, `B77W.png`, `B788.png`, `B789.png` |

| `images/aircraft/AAY/` | `A320.png` |

| `images/aircraft/ACA/` | `A21N.png`, `A333.png`, `B77W.png`, `B789.png` |

| `images/aircraft/AFR/` | `A359.png`, `B77W.png` |

| `images/aircraft/AMX/` | `B38M.png`, `B789.png` |

| `images/aircraft/ANA/` | `B77W.png`, `B789.png` |

| `images/aircraft/ASA/` | `B39M.png`, `B738.png`, `B739.png` |

| `images/aircraft/AVA/` | `A320.png`, `B788.png` |

| `images/aircraft/BAW/` | `A35K.png`, `B772.png`, `B788.png` |

| `images/aircraft/CCA/` | `B77W.png` |

| `images/aircraft/CMP/` | `B38M.png` |

| `images/aircraft/CPA/` | `A359.png`, `B77W.png` |

| `images/aircraft/DAL/` | `A21N.png`, `A321.png`, `A339.png`, `A359.png`, `B739.png`, `B752.png`, `B763.png`, `BCS1.png`, `BCS3.png` |

| `images/aircraft/DLH/` | `A359.png`, `B748.png` |

| `images/aircraft/EDV/` | `CRJ9.png` |

| `images/aircraft/EIN/` | `A21N.png`, `A333.png` |

| `images/aircraft/ENY/` | `E145.png`, `E75L.png` |

| `images/aircraft/ETD/` | `B789.png` |

| `images/aircraft/EVA/` | `B77W.png`, `B789.png` |

| `images/aircraft/FDX/` | `B752.png`, `B763.png`, `B77L.png`, `MD11.png` |

| `images/aircraft/FFT/` | `A20N.png`, `A21N.png`, `A320.png`, `A321.png` |

| `images/aircraft/FIN/` | `A359.png` |

| `images/aircraft/GTI/` | `B744.png`, `B748.png` |

| `images/aircraft/HAL/` | `A21N.png`, `A332.png` |

| `images/aircraft/IBE/` | `A333.png` |

| `images/aircraft/ICE/` | `B38M.png` |

| `images/aircraft/JAL/` | `A359.png`, `B77W.png` |

| `images/aircraft/JBU/` | `A21N.png`, `A320.png`, `BCS3.png` |

| `images/aircraft/JIA/` | `CRJ7.png`, `CRJ9.png` |

| `images/aircraft/JZA/` | `CRJ9.png`, `DH8D.png` |

| `images/aircraft/KAL/` | `A333.png`, `B77W.png`, `B789.png` |

| `images/aircraft/KLM/` | `A333.png`, `B77W.png`, `B789.png` |

| `images/aircraft/LAN/` | `B789.png` |

| `images/aircraft/NKS/` | `A20N.png`, `A21N.png`, `A320.png`, `A321.png` |

| `images/aircraft/PDT/` | `E145.png` |

| `images/aircraft/QFA/` | `B789.png` |

| `images/aircraft/QTR/` | `A35K.png`, `B77W.png`, `B789.png` |

| `images/aircraft/QXE/` | `E75L.png` |

| `images/aircraft/RPA/` | `E75L.png` |

| `images/aircraft/SAS/` | `A333.png` |

| `images/aircraft/SCX/` | `B738.png` |

| `images/aircraft/SIA/` | `A359.png`, `B77W.png` |

| `images/aircraft/SKW/` | `CRJ2.png`, `CRJ7.png`, `E75L.png` |

| `images/aircraft/SWA/` | `B38M.png`, `B737.png`, `B738.png` |

| `images/aircraft/SWR/` | `A333.png`, `B77W.png` |

| `images/aircraft/TAP/` | `A339.png` |

| `images/aircraft/THY/` | `A359.png`, `B77W.png` |

| `images/aircraft/UAE/` | `A388.png`, `B77W.png` |

| `images/aircraft/UAL/` | `A21N.png`, `A319.png`, `A320.png`, `B38M.png`, `B39M.png`, `B738.png`, `B739.png`, `B752.png`, `B753.png`, `B763.png`, `B772.png`, `B77W.png`, `B788.png`, `B789.png`, `B78X.png` |

| `images/aircraft/UPS/` | `B744.png`, `B748.png`, `B752.png`, `B763.png`, `MD11.png` |

| `images/aircraft/VIR/` | `A339.png`, `B789.png` |

| `images/aircraft/WJA/` | `B38M.png`, `B737.png`, `B789.png` |

| `images/aircraft/_generic/` | `BE20.png`, `BE58.png`, `C172.png`, `C208.png`, `C25B.png`, `C56X.png`, `CL35.png`, `EC35.png`, `GLF6.png`, `P28A.png`, `PC12.png` |


## Installing newly uploaded files

After uploading through GitHub:

```sh
cd ~/adsb_radar
git pull --ff-only
sudo ./install.sh
```

The installed copy is `/var/lib/adsb-radar/images/`. Installation adds/replaces supplied files and retains locally installed files absent from the checkout. To remove a previously installed image, delete that exact file from the installed asset directory and restart the display service. The `--purge` uninstaller removes all installed artwork.
