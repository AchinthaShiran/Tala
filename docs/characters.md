# Pet characters

## Built-in characters

Pick one in **Settings → Pet**. They are drawn in code, so they stay sharp at any size and every one of them
follows your pointer with its eyes and shows all the emotions.

| Character | Who |
| --- | --- |
| Robot | The original |
| Nexo | The Loyal Robot Companion: white robot with cat ears and glowing headphones |
| Kiko | The Curious Fox |
| Momo | The Digital Cat: black, with glowing cyan eyes and a curling tail |
| Lumi | The Holographic Spirit: a translucent ghost with an orbiting ring |
| ZEN | The Little Alien |
| Owlly | The Cyber Owl: big ringed eyes and a beak |
| Slimey | The AI Slime |
| PupBot | The Robo Pup: floppy ears and a wagging tail |

Each has a mood light in a different place (forehead, collar, bell, antenna ...) that glides between colours as
the assistant works.

## Your own artwork

The desktop pet can also wear your own artwork instead. A character is a folder of images, one per
expression.

## Quick start

1. Open **Settings → Pet** and press **Create an example to edit**. This writes a working character called
   `example-robot` and opens its folder.
2. Replace the images with yours, keeping the file names.
3. Back in **Settings → Pet** press **Refresh**, pick your folder from the list, and **Save**.

You can also create the folder yourself: `<config folder>/characters/<name>/`. **Open characters folder** in
the Pet tab shows where that is.

## Files

Only `neutral.png` is required. Anything missing falls back to the closest image that exists, so you can
start with one picture and add expressions over time.

| File | Shown when | Falls back to |
| --- | --- | --- |
| `neutral.png` | normal, and for anything missing | (required) |
| `happy.png` | after a reply, clicked, put down | neutral |
| `love.png` | petted for a few seconds, double-clicked | happy |
| `surprised.png` | the pointer arrives, picked up, woken | neutral |
| `sad.png` | something went wrong | neutral |
| `curious.png` | waiting for your approval | neutral |
| `dizzy.png` | shaken | surprised |
| `tired.png` | the battery is low | sleepy, then sad |
| `charging.png` | just plugged in | happy |
| `sleepy.png`, `sleeping.png` | left alone for a while | each other |
| `thinking.png` | working on a request | neutral |
| `talking.png` | replying | neutral (it pulses while talking) |
| `blink.png` | the brief blink while neutral | (skipped) |

`.png`, `.webp` and `.jpg` work. Use a transparent background, one character per image, all images the same
size and framing, roughly 256 to 512 pixels square (the limit is 4096). An optional `character.yaml` sets the
display name: `name: Kiko the Fox`.

## What the pet adds on top of your art

Hopping when clicked, squashing when it lands, tilting toward the pointer, a small shift of the whole picture
toward the pointer, bobbing, a pulse while talking, and the floating hearts, sparkles, "z"s, "?" and tear. You
do not draw those. Eyes that follow the pointer exactly are only possible with the built-in robot, because
your images are flat pictures.

If a character cannot be loaded (missing `neutral.png`, an unreadable image) the pet keeps the previous look
and the chat shows what is wrong.
