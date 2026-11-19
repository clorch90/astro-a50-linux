-- Keeps the Logitech A50 pinned to the "pro-audio" ALSA profile.
--
-- GNOME Settings' Sound panel doesn't know about Pro Audio and switches the
-- card back to a plain stereo profile (with save=true) whenever it is
-- touched there, which collapses the Voice/Game outputs back into one.
-- This hook watches for that and immediately switches the A50 back to
-- Pro Audio.

cutils = require ("common-utils")
log = Log.open_topic ("s-a50-lock-pro-audio")

SimpleEventHook {
  name = "device/lock-a50-pro-audio",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "device-params-changed" },
      Constraint { "event.subject.param-id", "=", "Profile" },
    },
  },
  execute = function (event)
    local device = event:get_subject ()

    if device.properties ["api.alsa.card.name"] ~= "A50" then
      return
    end

    local active_profile = nil
    for p in device:iterate_params ("Profile") do
      active_profile = cutils.parseParam (p, "Profile")
    end

    if not active_profile or active_profile.name == "pro-audio" then
      return
    end

    for p in device:iterate_params ("EnumProfile") do
      local candidate = cutils.parseParam (p, "EnumProfile")
      if candidate and candidate.name == "pro-audio" then
        log:notice (device, "A50 profile changed to '" .. active_profile.name ..
            "', forcing it back to 'pro-audio'")
        local param = Pod.Object {
          "Spa:Pod:Object:Param:Profile", "Profile",
          index = tonumber (candidate.index),
        }
        device:set_param ("Profile", param)
        break
      end
    end
  end
}:register ()
