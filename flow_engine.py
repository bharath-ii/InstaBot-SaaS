def parse_keyword_from_label(label):
    if 'Trigger: "' in label:
        return label.split('Trigger: "')[1].split('"')[0].lower()
    return None

def parse_message_from_label(label):
    if 'Message: "' in label:
        return label.split('Message: "')[1].split('"')[0]
    return label

def find_node(nodes, node_id):
    for n in nodes:
        if n['id'] == node_id:
            return n
    return None

def get_next_node(edges, current_node_id):
    for edge in edges:
        if edge['source'] == current_node_id:
            return edge['target']
    return None

def evaluate_flow(flow_data, text, current_state_node_id=None):
    """
    Evaluates a flow. 
    If current_state_node_id is None, it looks for a matching trigger.
    Returns (reply_message_text, next_state_node_id)
    """
    if not flow_data or 'nodes' not in flow_data or 'edges' not in flow_data:
        return None, None
        
    nodes = flow_data['nodes']
    edges = flow_data['edges']
    text = text.lower()

    if not current_state_node_id:
        # Find matching trigger
        start_node = None
        for node in nodes:
            if 'Trigger' in node['data']['label']:
                keyword = parse_keyword_from_label(node['data']['label'])
                if keyword and keyword in text:
                    start_node = node
                    break
        
        if not start_node:
            return None, None
            
        next_node_id = get_next_node(edges, start_node['id'])
    else:
        # User is already in a flow, move to the next step
        next_node_id = get_next_node(edges, current_state_node_id)

    if not next_node_id:
        return None, None

    next_node = find_node(nodes, next_node_id)
    if not next_node:
        return None, None

    label = next_node['data']['label']
    
    if 'Message' in label:
        msg = parse_message_from_label(label)
        # Check if there's a Wait node after this message
        wait_node_id = get_next_node(edges, next_node['id'])
        if wait_node_id:
            wait_node = find_node(nodes, wait_node_id)
            if wait_node and 'Wait' in wait_node['data']['label']:
                return msg, wait_node_id
        return msg, None

    return None, None
