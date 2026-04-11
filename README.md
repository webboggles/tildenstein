# TILDENSTEIN 3D

Wolfenstein-style raycasting FPS for the [Tildagon badge](https://tildagon.badge.emfcamp.org/) at EMF Camp.

## Features

- Raycasting 3D engine with textured walls, tents &amp; marquees
- ESP-NOW mesh multiplayer &mdash; shoot other players as spiders
- Procedural map of EMF Camp grounds with water, footpaths &amp; streams
- Jump, dodge &amp; regenerate health
- LED peer radar &mdash; directional indicators for nearby players
- IMU-driven parallax on title &amp; credits screens

## Controls

| Button | Action |
|--------|--------|
| IMU (tilt) | Move &amp; strafe |
| B (Right) | Shoot |
| F (Cancel) | Jump |
| A (Confirm) | Menu select |

## Install

Available from the [Tildagon App Store](https://apps.badge.emfcamp.org/) or copy files manually via `mpremote`:

```
mpremote cp app.py :/apps/tildenstein/app.py
mpremote cp engine.py :/apps/tildenstein/engine.py
mpremote cp game_map.py :/apps/tildenstein/game_map.py
mpremote cp net.py :/apps/tildenstein/net.py
mpremote cp logo.jpg :/apps/tildenstein/logo.jpg
mpremote cp tildagon.toml :/apps/tildenstein/tildagon.toml
```

## Credits

[@webboggles](https://github.com/webboggles) &mdash; [weborder.uk](https://weborder.uk)

## Licence

CC-BY-NC-4.0
