import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

def make_overlay_element():
    """
    Placeholder overlay element.
    Replace with a bin later, e.g.:
      Gst.parse_bin_from_description("timeoverlay shaded-background=true", True)
    """
    return Gst.ElementFactory.make("identity", "overlay")
