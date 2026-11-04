# Miniem for Home Assistant

Lets Home Assistant put cards on the [Miniem](https://github.com/klmz/miniem-android)
launcher's panel, the one you get by swiping up from home. A card is a small UI that
Home Assistant describes and the phone draws: text, buttons, text fields, switches,
sliders, selects, live entity states and camera images. Pressing a button fires a
`miniem_action` event that your automation can wait for.

## Install

1. HACS → ⋮ → *Custom repositories* → add this repository as an **Integration**, then
   install **Miniem** and restart Home Assistant.
2. *Settings → Devices & services → Add integration → Miniem*. Paste the JSON key of a
   Firebase service account that can send Cloud Messaging. In the Firebase console:
   *Project settings → Service accounts → Generate new private key*. The default
   `firebase-adminsdk` account already has the role it needs.
3. In the launcher, swipe up and fill in this Home Assistant's address and a long-lived
   access token (*your profile → Security*). The phone then appears as a device here.

## Actions

### `miniem.show_card`

| field | |
|---|---|
| `device_id` | Miniem phone device(s). Leave empty for all. |
| `card` | `id`, `title`, `subtitle`, `body`. A card with the same id replaces the old one. |
| `focus` | `true` brings the launcher up on the panel now. `false` shows only a dot under the clock. |
| `ttl` | Seconds until the card goes away by itself. |
| `priority` | Higher sorts first. |
| `notification_title` / `notification_body` | For the notification posted when the panel cannot be brought up. |

### `miniem.clear_card`

`card_id`, plus optional `device_id`.

## Event `miniem_action`

```yaml
device_id: <device registry id>
device_name: Google Pixel 9
card_id: blinds_auto_open
action: undo            # the event name, the service, or "dismiss"
data: {}                # the action's own data
values: {note: "…"}     # every input on the card
```

## Example

```yaml
- action: miniem.show_card
  data:
    ttl: 600
    card:
      id: blinds_auto_open
      title: Blinds opened
      body:
        - {type: text, text: "The bedroom blinds just opened."}
        - type: row
          children:
            - {type: button, label: Undo, style: danger, action: undo}
            - {type: button, label: Fine, action: {type: dismiss}}
- wait_for_trigger:
    - trigger: event
      event_type: miniem_action
      event_data: {card_id: blinds_auto_open, action: undo}
  timeout: "00:10:00"
  continue_on_timeout: false
- action: cover.close_cover
  target: {entity_id: cover.bedroom_blinds}
```

The full card vocabulary is in
[docs/home-assistant.md](https://github.com/klmz/miniem-android/blob/main/docs/home-assistant.md).

## Blueprint: do it, then offer an undo

`blueprints/automation/miniem/undo_card.yaml` takes a trigger, your actions and the
entities to restore. It snapshots those entities, runs the actions, then shows a card
with **Undo** and **Keep**. Undo restores the snapshot. Import it from
*Settings → Automations → Blueprints → Import* with this file's GitHub URL.
