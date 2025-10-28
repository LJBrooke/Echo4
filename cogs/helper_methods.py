def _get_coms_by_skill(skill: str, com_data: tuple):
    if '(' in skill:
        skill = skill[:skill.find('(')]
    found = False
    response =[]
    response.append(f'\n\n## Class Mods with {skill}')
    for class_mod in com_data.get('class mods'):
        if skill.strip() in class_mod.get("skills"):
            found=True
            response.append(f"\n### {class_mod.get('name')}:")
            for key, value in class_mod.items():
                # Skip the name key as we manually add it as a heading.
                if key not in ['name', 'lootlemon'] and value is not None:
                    formatted_key = key.replace('_', ' ').title()
                    response.append(f"- **{formatted_key}**: {value}")
                elif key=='lootlemon' and value is not None:
                    formatted_key = key.replace('_', ' ').title()
                    response.append(f"- [Lootlemon Page](<{value}>)")
    if found: return "\n".join(response), False
    return None, True

def get_coms_by_name(com_name: str, com_data: tuple):
    found = False
    response =[]
    vault_hunter = None
    # response.append(f'\n\n## {com_name}')
    for class_mod in com_data.get('class mods'):
        if com_name.strip() in class_mod.get("name"):
            found=True
            vault_hunter = class_mod.get("character")
            response.append(f"# {class_mod.get('name')}:")
            for key, value in class_mod.items():
                # Skip the 'character' key, we already have character context from the skill.
                # Skip the name key as we manually add it as a heading.
                if key not in ['character', 'name', 'lootlemon'] and value is not None:
                    formatted_key = key.replace('_', ' ').title()
                    response.append(f"- **{formatted_key}**: {value}")
                elif key=='lootlemon' and value is not None:
                    formatted_key = key.replace('_', ' ').title()
                    response.append(f"- [Lootlemon Page](<{value}>)")
            break
    if found: return "\n".join(response), vault_hunter, False
    return None, True

def _process_lookup(name: str, com: int, skill_data: tuple, com_data: tuple):
    """
    Returns all information on a provided Skill or Item name.

    Returns:
        Str: String formatted for a Discord respnse listing properties of searched skill/item.
    """
   
    found_items = []
    
    # Pre-process the search name once to be more efficient
    search_name = name.lower().strip()

    # 2. Search through all data without breaking after the first match.
    for parent_key, items in skill_data.items():
        for item in items:
            # 3. Use the 'in' operator for substring search.
            if search_name in item.get('name', '').lower().strip():
                # Add a dictionary containing both the item and its source to our list.
                found_items.append({'item': item, 'source': parent_key})

    # --- Check class mods ---
    
    ephemeral_state=False
    if com==1:
        coms, ephemeral_state = _get_coms_by_skill(name, com_data)
    # --- Format and Send the Response ---

    # 4. Check if the list of found items is empty.
    if not found_items:
        if not coms:
            return f"Could not find any skill information for `{name}`.", True
        return f"Could not find any skill information for `{name}`." + coms, ephemeral_state

    # 5. Build the response message.
    # Start with a summary of how many results were found.
    response_lines = [f"🔎 Found **{len(found_items)}** results for: **{name}**"]

    # Loop through each match you found.
    for match in found_items:
        item_data = match['item']
        source_key = match['source']

        # Add a separator and a main header for each item for clarity.
        response_lines.append("\n---")
        response_lines.append(f"**# {item_data.get('name')}**")
        
        # Add the source.
        response_lines.append(f"- **Source**: {source_key}")

        # Add all other details from the item's dictionary.
        for key, value in item_data.items():
            # Skip the 'name' key since we already used it in the header.
            if key != 'name' and value is not None:
                formatted_key = key.replace('_', ' ').title()
                response_lines.append(f"- **{formatted_key}**: {value}")

    final_response = "\n".join(response_lines)
    
    if com==1: final_response = str(final_response) + str(_get_coms_by_skill(name))
    
    # Note: Discord messages have a 2000 character limit. 
    if len(final_response) > 2000:
        final_response = final_response[:1985] + "\n... (truncated)"
    return final_response, ephemeral_state