def binary_search_ticket(tickets, target_id):
    """
    Бинарный поиск тикета по ID в отсортированном списке[cite: 2].
    tickets: список объектов или словарей из БД.
    """
    low = 0
    high = len(tickets) - 1

    while low <= high:
        mid = (low + high) // 2
        if tickets[mid].id == target_id:
            return tickets[mid]
        elif tickets[mid].id < target_id:
            low = mid + 1
        else:
            high = mid - 1
    return None