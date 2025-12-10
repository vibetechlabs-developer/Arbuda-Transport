def global_data(request):
    
    return {
        'company_info' :  request.session.get('company_info')
        , 'company_profile' : request.session.get('company_profile')
    }