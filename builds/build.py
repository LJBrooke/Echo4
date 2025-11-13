import urllib
import json

try:
    with open('data/Skill Trees.json', 'r', encoding='utf-8') as f:
        SKILL_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/Skill Trees.json: {e}")
    SKILL_DATA = {}

class SkillBuild:
    def __init__(self, vh: str | None = None, skills: dict[str, int] = {}, action_skill: str | None = None, augment: str | None = None, capstone: str | None = None):
        self.vh = vh
        self.skills = skills
        self.action_skill = action_skill
        self.augment = augment
        self.capstone = capstone

    @staticmethod
    def from_lootlemon(url: str) -> 'SkillBuild':
        """Create a SkillBuild from a LootLemon URL."""
        # Example URL: https://www.lootlemon.com/class/vex#xxx_00000000000.000000.000000.000000_00000000000.000000.000000.000000_00000000000.000000.000000.000000
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != 'www.lootlemon.com':
            raise ValueError(f'{url} is not a valid LootLemon URL.')
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) < 2 or path_parts[0] != 'class':
            raise ValueError(f'{url} is not a valid LootLemon class URL.')
        vh = path_parts[1]
        fragment = parsed.fragment
        if not fragment:
            raise ValueError(f'{url} does not contain skill build information.')
        # Further parsing of the fragment can be added here to extract skill build details
        return SkillBuild(vh=vh)

class Build:
    def __init__(self, skills: SkillBuild = SkillBuild(), specializations=None, gear=None):
        # use internal attributes so properties can manage access
        self._skills = skills
        self._specializations = specializations
        self._gear = gear

    @property
    def skills(self):
        """Skills for the build."""
        return self._skills

    @skills.setter
    def skills(self, skills):
        self._skills = skills

    @property
    def specializations(self):
        """Specializations for the build."""
        return self._specializations

    @specializations.setter
    def specializations(self, specializations):
        self._specializations = specializations

    @property
    def gear(self):
        """Gear for the build."""
        return self._gear

    @gear.setter
    def gear(self, gear):
        self._gear = gear
