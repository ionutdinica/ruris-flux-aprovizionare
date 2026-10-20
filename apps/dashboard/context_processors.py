from .navigation import build_menu


def navigation(request):
    """Pune meniul la dispoziția tuturor șabloanelor, ca variabila `menu`.

    Un „context processor” rulează automat la afișarea oricărei pagini,
    așa că nicio pagină nu trebuie să construiască meniul singură.
    """
    if not request.user.is_authenticated:
        return {}
    return {"menu": build_menu(request.user, request.path)}
