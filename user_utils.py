"""
User utilities â€” display name generation and user management.
"""

import random

ADJECTIVES = [
    "Curious", "Lazy", "Brave", "Sneaky", "Clever", "Cosmic", "Funky",
    "Happy", "Chill", "Wild", "Witty", "Bold", "Swift", "Lucky", "Zen",
    "Spicy", "Fuzzy", "Quirky", "Mighty", "Groovy", "Mellow", "Perky",
    "Zany", "Snappy", "Dapper", "Jolly", "Plucky", "Cheeky", "Sassy",
    "Bouncy", "Rustic", "Stormy", "Frosty", "Sunny", "Misty", "Peppy",
    "Giddy", "Nifty", "Wacky", "Dizzy"
]

ANIMALS = [
    "Otter", "Penguin", "Fox", "Panda", "Koala", "Owl", "Wolf",
    "Rabbit", "Falcon", "Dolphin", "Tiger", "Bear", "Hawk", "Lynx",
    "Moose", "Raven", "Gecko", "Sloth", "Badger", "Parrot", "Jaguar",
    "Walrus", "Ferret", "Toucan", "Meerkat", "Narwhal", "Lemur",
    "Flamingo", "Hedgehog", "Capybara", "Quokka", "Axolotl", "Wombat",
    "Pangolin", "Mantis", "Osprey", "Llama", "Bison", "Crane", "Orca"
]


def generate_display_name() -> str:
    """Generate a fun random display name like CuriousOtter42."""
    adj = random.choice(ADJECTIVES)
    animal = random.choice(ANIMALS)
    num = random.randint(1, 99)
    return f"{adj}{animal}{num}"
