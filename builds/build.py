import urllib.parse
import json

try:
    with open('data/Skill Trees.json', 'r', encoding='utf-8') as f:
        SKILL_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading data/Skill Trees.json: {e}")
    SKILL_DATA = {}

# Constants for handling offsets between lootlemon URL encoding and SKILL_DATA indices for augments and capstones
# Probably this should be handled by traversing the SKILL_DATA structure directly instead of hardcoding these values,
# but they are consistent and this is easier.
AUGMENTS_PER_TREE = 5
CAPSTONES_PER_TREE = 3

def _build_skills_by_name():
    """Build a dictionary mapping skill names to enriched skill data including vault hunter, tree, and subtree."""
    skills_by_name = {}
    augments_by_name = {}
    capstones_by_name = {}
    
    for vh_key, vh_data in SKILL_DATA.items():
        for tree in vh_data.get('trees', []):
            tree_name = tree.get('name')
            
            # Process regular skills
            for subtree_name, skills_list in tree.get('skills', {}).items():
                for skill in skills_list:
                    name = skill.get('name')
                    if name:
                        skills_by_name[name] = {
                            **skill,
                            'vault_hunter': vh_key,
                            'tree': tree_name,
                            'subtree': subtree_name
                        }
            
            # Process augments
            for augment in tree.get('augments', []):
                name = augment.get('name')
                if name:
                    augments_by_name[name] = {
                        **augment,
                        'vault_hunter': vh_key,
                        'tree': tree_name,
                    }
            
            # Process capstones
            for capstone in tree.get('capstones', []):
                name = capstone.get('name')
                if name:
                    capstones_by_name[name] = {
                        **capstone,
                        'vault_hunter': vh_key,
                        'tree': tree_name,
                    }
    
    return {"skills": skills_by_name, "augments": augments_by_name, "capstones": capstones_by_name}

# Build the skills_by_name dictionary at module load time
SKILLS_BY_NAME = _build_skills_by_name()

def _letter_to_index(letter: str) -> int:
    """Convert a lowercase letter to a zero-based index (a=0, b=1, c=2, ...)."""
    return ord(letter) - ord('a')
def _index_to_letter(index: int) -> str:
    """Convert a zero-based index to a lowercase letter (0=a, 1=b, 2=c, ...)."""
    return chr(ord('a') + index)

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
        # Example URL: https://www.lootlemon.com/class/amon#xxx_00000000000.000000.000000.000000_00000000000.000000.000000.000000_00000000000.000000.000000.000000
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != 'www.lootlemon.com':
            raise ValueError(f'{url} is not a LootLemon URL.')
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) < 2 or path_parts[0] != 'class':
            raise ValueError(f'{url} is not a valid LootLemon class URL.')
        vh = path_parts[1]
        build = SkillBuild(vh=vh, skills={})
        fragment = parsed.fragment
        if not fragment:
            raise ValueError(f'{url} does not contain skill build information.')
        # Parsing the lootlemon build data format:
        # There are 4 segments separate by underscores.
        # The first is action skills, with a character for action skill, augment, and capstone.
        # The next three are skill tiers for green, blue, and red trees.
        # These list the skill level of each skill in order reading left to right by row within each subtree.
        # Subtrees are separated by periods.
        # The JSON skill data is structured so that the indices line up with this format.
        action_skills, *trees = fragment.split('_')
        action_skill, augment, capstone = list(action_skills)
        action_skill_tree = None
        # x means no selection
        if action_skill != 'x':
            tree_index = _letter_to_index(action_skill)
            action_skill_tree = SKILL_DATA[vh]["trees"][tree_index]
            build.action_skill = action_skill_tree["action_skill"]["name"]
            if augment != 'x':
                build.augment = action_skill_tree["augments"][_letter_to_index(augment) - tree_index * AUGMENTS_PER_TREE]["name"]
            if capstone != 'x':
                build.capstone = action_skill_tree["capstones"][_letter_to_index(capstone) - tree_index * CAPSTONES_PER_TREE]["name"]

        # Parse skill levels
        for tree_index, tree_data in enumerate(trees):
            tree = SKILL_DATA[vh]["trees"][tree_index]
            subtree_levels = tree_data.split('.')
            for subtree_index, subtree_level in enumerate(subtree_levels):
                subtree = tree["skills"][list(tree["skills"].keys())[subtree_index]]
                for skill_index, level_char in enumerate(subtree_level):
                    level = int(level_char)
                    if level > 0:
                        skill_name = subtree[skill_index]["name"]
                        build.skills[skill_name] = level

        return build

    def pretty_print(self, stream=None) -> None:
        """Print a human-readable summary of this SkillBuild to the given stream.

        If stream is None the output is written to sys.stdout.
        """
        import sys
        out = stream or sys.stdout
        def write(s=""):
            out.write(s + "\n")

        write(f"Vault Hunter: {self.vh}")
        write(f"Action skill: {self.action_skill or 'None'}")
        write(f"Augment: {self.augment or 'None'}")
        write(f"Capstone: {self.capstone or 'None'}")
        write("Allocated skills:")
        # Sort skills alphabetically for stable output
        for name, pts in sorted(self.skills.items(), key=lambda kv: kv[0].lower()):
            write(f"  - {name}: {pts}")

    def to_lootlemon(self) -> str:
        """Serialize this SkillBuild into a LootLemon class URL.

        Returns a string like: https://www.lootlemon.com/class/<vh>#<fragment>
        where the fragment matches the format parsed by `from_lootlemon`.
        """
        if not self.vh:
            raise ValueError("vh is required to serialize to a LootLemon URL")

        vh = self.vh

        action_char = 'x'
        augment_char = 'x'
        capstone_char = 'x'

        trees = SKILL_DATA.get(vh, {}).get('trees', [])
        # Look for the selection action skill, augment, and capstone to determine their character representations in lootlemon.
        if self.action_skill:
            for tree_index, tree in enumerate(trees):
                action_skill = tree.get('action_skill', {})
                if action_skill and action_skill.get('name') == self.action_skill:
                    action_char = _index_to_letter(tree_index)
                    if self.augment:
                        for augment_index, augment in enumerate(tree.get('augments', [])):
                            if augment.get('name') == self.augment:
                                augment_char = _index_to_letter(augment_index + tree_index * AUGMENTS_PER_TREE)
                                break
                    if self.capstone:
                        for capstone_index, capstone in enumerate(tree.get('capstones', [])):
                            if capstone.get('name') == self.capstone:
                                capstone_char = _index_to_letter(capstone_index + tree_index * CAPSTONES_PER_TREE)
                                break
                    break

        # Build tree skill strings for each of the three trees in order
        tree_fragments = []
        for tree_index, tree in enumerate(trees):
            skill_sub_fragments = []
            for subtree in tree.get('skills', {}).values():
                chars = []
                for skill in subtree:
                    name = skill.get('name')
                    pts = int(self.skills.get(name, 0))
                    chars.append(str(pts))
                skill_sub_fragments.append(''.join(chars))
            tree_fragments.append('.'.join(skill_sub_fragments))

        fragment = f"{action_char}{augment_char}{capstone_char}_" + "_".join(tree_fragments)
        return f"https://www.lootlemon.com/class/{vh}#{fragment}"

class Build:
    def __init__(self, skills: SkillBuild = SkillBuild(), specializations=None, gear=None):
        # use internal attributes so properties can manage access
        self.skills = skills
        self.specializations = specializations
        self.gear = gear

if __name__ == "__main__":
    build = SkillBuild.from_lootlemon("https://www.lootlemon.com/class/rafa#bff_0100000000.00000.000000.00000_0550000410.05512.05000.50055_0000000000.000000.000000.00000")
    build.pretty_print()
    print(build.to_lootlemon())
    build2 = SkillBuild.from_lootlemon("https://www.lootlemon.com/class/vex#xxx_00000000000.000000.000000.000000_00000000000.000000.000000.000000_00000000000.000000.000000.000000")
    build2.pretty_print()
    print(build2.to_lootlemon())