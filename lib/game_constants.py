"""Game constants and configuration."""

# Delay configurations (in milliseconds)
class DELAY_CONFIG:
    """Timing configurations for game flow."""
    DIALOGUE = 2000  # General dialogue delay
    LONG = 3000  # Long delay for important messages
    NIGHT_RESOLVE = 2000  # Night resolution delay


# Game configuration
class GAME_CONFIG:
    """General game configuration."""
    MAX_REVOTE_COUNT = 3  # Maximum number of wolf revotes


# Temperature for AI decisions
GAME_TEMPERATURE = 0.7
