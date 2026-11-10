"""Portfolio Exposure Graph: explainable direct, look-through and supplier exposures."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("portfolio-exposure-graph")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"
