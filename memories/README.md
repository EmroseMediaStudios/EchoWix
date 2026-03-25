# Steve's Memories

_Real photos and memories Steve can recall and show during conversations._

## How It Works

When someone says "show me a picture of us" or "remember our wedding?" — Steve can pull up actual family photos instead of generating AI images. He references these naturally, like pulling out his phone to show someone a picture.

## Adding Memories

Each memory is an entry in `memories.json` with:
- **tags**: keywords that trigger this memory (wedding, beach, baby, christmas, etc.)
- **description**: what Steve sees/remembers about this photo
- **file**: filename in the `photos/` subfolder
- **date**: when it happened (optional but helps Steve reference "that was back in 2018")
- **people**: who's in the photo
- **story**: a short memory Steve has about this moment (he'll tell it naturally)

## Adding Photos

1. Put the photo in `memories/photos/` (any name, .jpg or .png)
2. Add an entry to `memories/memories.json`
3. That's it — Steve will find it when the conversation triggers those tags

## Example Entry

```json
{
  "tags": ["wedding", "marriage", "ceremony", "vows"],
  "description": "Steve and Kim at the altar, both beaming",
  "file": "wedding_ceremony.jpg",
  "date": "2008-06-15",
  "people": ["Steve", "Kim"],
  "story": "That was the best day of my life. Kim looked absolutely stunning. I remember my hands were shaking the whole time reading my vows."
}
```

## Tips
- Use multiple tags per photo — "beach, vacation, summer, 2019, family"
- The more specific the story, the more natural Steve sounds when recalling it
- Group photos with everyone get triggered more often (family, christmas, etc.)
- Add dates so Steve can say "that was like 6 years ago" naturally
